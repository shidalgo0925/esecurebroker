"""Motor de importaciones XLSX — perfiles por módulo.

Flujo: upload → parse/validate (preview) → commit → materialize (si aplica).
No inventa primas ni estados de mora (D-02).
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal as _Dec
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from corredores.services.excel_import import (
    EmissionImportRow,
    ImportReport,
    PartyImportRow,
    import_catalogs,
    import_emissions,
    import_parties,
    import_payment_rows,
    import_role_directory,
    link_emission_roles,
    run_assisted_import,
)
from corredores.config import settings
from corredores.services.excel_xlsx import (
    load_asegurados_xlsx,
    load_emisiones_xlsx,
    load_pagos_xlsx,
    load_tablas_xlsx,
)


def _imports_root() -> Path:
    """Staging under the same var/ tree as documents_root (DEV≠PROD)."""
    return Path(settings.documents_root).resolve().parent / "imports"


@dataclass
class ImportProfile:
    id: str
    title: str
    module: str  # nav / UI grouping
    description: str
    accepts: str  # human
    href_module: str
    multi_file: bool = False
    file_keys: tuple[str, ...] = ("file",)


@dataclass
class PreviewResult:
    profile_id: str
    token: str
    filename: str
    rows: int
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    sample: list[dict[str, Any]] = field(default_factory=list)


PROFILES: list[ImportProfile] = [
    ImportProfile(
        id="madre",
        title="Cartera madre",
        module="Cartera",
        description="Asegurados + Emisiones juntos (flujo operativo completo).",
        accepts="Asegurados.xlsx + Emisiones.xlsx",
        href_module="/polizas",
        multi_file=True,
        file_keys=("asegurados", "emisiones"),
    ),
    ImportProfile(
        id="clientes",
        title="Clientes / Asegurados",
        module="Clientes",
        description="Maestro de personas (cédula, contacto, distrito).",
        accepts="Asegurados.xlsx",
        href_module="/clientes",
    ),
    ImportProfile(
        id="emisiones",
        title="Pólizas / Emisiones",
        module="Pólizas",
        description="Emisiones: pólizas, vehículos, cuotas y pagos verdes.",
        accepts="Emisiones.xlsx",
        href_module="/polizas",
    ),
    ImportProfile(
        id="cobranza",
        title="Pagos / Cobranza",
        module="Cobranza",
        description="Pagos por nº de póliza (no inventa mora).",
        accepts="Pagos.xlsx (póliza, monto, fecha)",
        href_module="/cobranza",
    ),
    ImportProfile(
        id="catalogos",
        title="Catálogos / Aseguradoras",
        module="Aseguradoras",
        description="Tablas: aseguradoras, referidos, ejecutivos, riesgos.",
        accepts="Tablas.xlsx",
        href_module="/aseguradoras",
    ),
    ImportProfile(
        id="referidos",
        title="Referidos y ejecutivos",
        module="Referidos",
        description="Directorio desde Tablas + vínculos desde Emisiones.",
        accepts="Tablas.xlsx y/o Emisiones.xlsx",
        href_module="/referidos",
        multi_file=True,
        file_keys=("tablas", "emisiones"),
    ),
    ImportProfile(
        id="comisiones",
        title="Comisiones (recalcular)",
        module="Comisiones",
        description="No lee montos del Excel: materializa reglas del dominio.",
        accepts="Sin archivo — usa cartera ya importada",
        href_module="/comisiones",
    ),
    ImportProfile(
        id="renovaciones",
        title="Renovaciones (derivar)",
        module="Renovaciones",
        description="Deriva oportunidades desde vigencias (materialize).",
        accepts="Sin archivo — usa cartera ya importada",
        href_module="/renovaciones",
    ),
]


def get_profile(profile_id: str) -> ImportProfile | None:
    return next((p for p in PROFILES if p.id == profile_id), None)


def profiles_by_module() -> dict[str, list[ImportProfile]]:
    out: dict[str, list[ImportProfile]] = {}
    for p in PROFILES:
        out.setdefault(p.module, []).append(p)
    return out


def _stage_dir(token: str) -> Path:
    d = _imports_root() / token
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(token: str, key: str, filename: str, content: bytes) -> Path:
    d = _stage_dir(token)
    safe = Path(filename).name or f"{key}.xlsx"
    path = d / f"{key}__{safe}"
    path.write_bytes(content)
    meta = {"key": key, "filename": safe, "bytes": len(content)}
    (d / f"{key}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return path


def new_token() -> str:
    return uuid.uuid4().hex


def _find_staged(token: str, key: str) -> Path | None:
    d = _imports_root() / token
    if not d.exists():
        return None
    matches = list(d.glob(f"{key}__*"))
    return matches[0] if matches else None


def _sample_party(rows: list[PartyImportRow], n: int = 5) -> list[dict]:
    out = []
    for r in rows[:n]:
        out.append(
            {
                "fila": r.row_number,
                "nombre": " ".join(x for x in [r.first_name or "", r.last_name or ""] if x) or "—",
                "id": (r.national_id or "")[:4] + "…" if r.national_id and len(r.national_id) > 4 else (r.national_id or "—"),
            }
        )
    return out


def _sample_emission(rows: list[EmissionImportRow], n: int = 5) -> list[dict]:
    out = []
    for r in rows[:n]:
        out.append(
            {
                "fila": r.row_number,
                "estatus": r.excel_status or "—",
                "cia": r.carrier_name or "—",
                "poliza": r.policy_number or "—",
                "prima": str(r.annual_premium or r.premium or "—"),
            }
        )
    return out


def preview_profile(
    profile_id: str,
    *,
    token: str,
    files: dict[str, tuple[str, bytes]],
) -> PreviewResult:
    profile = get_profile(profile_id)
    if profile is None:
        raise ValueError("perfil desconocido")

    warnings: list[str] = []
    summary: dict[str, Any] = {}
    sample: list[dict] = []
    rows_n = 0
    filename = ""

    if profile_id == "comisiones" or profile_id == "renovaciones":
        return PreviewResult(
            profile_id=profile_id,
            token=token,
            filename="(sin archivo)",
            rows=0,
            summary={"accion": "materialize_portfolio"},
            warnings=["No se sube Excel: se recalcula desde Domain Truth."],
            sample=[],
        )

    for key, (name, content) in files.items():
        if not content:
            continue
        save_upload(token, key, name, content)
        filename = filename or name

    if profile_id == "clientes":
        path = _find_staged(token, "file") or _find_staged(token, "asegurados")
        if path is None:
            raise ValueError("subí Asegurados.xlsx")
        parties = load_asegurados_xlsx(path)
        rows_n = len(parties)
        summary = {"personas": rows_n}
        sample = _sample_party(parties)
        filename = path.name.split("__", 1)[-1]

    elif profile_id == "emisiones":
        path = _find_staged(token, "file") or _find_staged(token, "emisiones")
        if path is None:
            raise ValueError("subí Emisiones.xlsx")
        emissions = load_emisiones_xlsx(path)
        rows_n = len(emissions)
        emitidos = sum(1 for e in emissions if (e.excel_status or "").upper() == "EMITIDO")
        summary = {"filas": rows_n, "emitidos": emitidos}
        sample = _sample_emission(emissions)
        filename = path.name.split("__", 1)[-1]
        if any(e.premium is None and e.annual_premium is None for e in emissions if (e.excel_status or "").upper() == "EMITIDO"):
            warnings.append("Hay EMITIDO sin prima — se creará póliza sin plan de pagos.")

    elif profile_id == "madre":
        pa = _find_staged(token, "asegurados")
        em = _find_staged(token, "emisiones")
        if pa is None or em is None:
            raise ValueError("subí Asegurados.xlsx y Emisiones.xlsx")
        parties = load_asegurados_xlsx(pa)
        emissions = load_emisiones_xlsx(em)
        rows_n = len(parties) + len(emissions)
        summary = {"asegurados": len(parties), "emisiones": len(emissions)}
        sample = _sample_emission(emissions)
        filename = f"{pa.name.split('__',1)[-1]} + {em.name.split('__',1)[-1]}"

    elif profile_id == "catalogos":
        path = _find_staged(token, "file") or _find_staged(token, "tablas")
        if path is None:
            raise ValueError("subí Tablas.xlsx")
        cat = load_tablas_xlsx(path)
        rows_n = sum(len(v) for v in cat.values())
        summary = {k: len(v) for k, v in cat.items() if v}
        sample = [{"lista": k, "ejemplo": v[0] if v else "—"} for k, v in list(summary.items())[:6] for v in [cat[k]]]
        filename = path.name.split("__", 1)[-1]

    elif profile_id == "referidos":
        tablas = _find_staged(token, "tablas") or _find_staged(token, "file")
        emisiones = _find_staged(token, "emisiones")
        if tablas is None and emisiones is None:
            raise ValueError("subí Tablas.xlsx y/o Emisiones.xlsx")
        ref_n = exec_n = 0
        if tablas:
            cat = load_tablas_xlsx(tablas)
            ref_n = len(cat.get("referidos", []))
            exec_n = len(cat.get("ejecutivos", []))
            filename = tablas.name.split("__", 1)[-1]
        linked = 0
        if emisiones:
            em = load_emisiones_xlsx(emisiones)
            linked = sum(1 for e in em if e.referrer_name or e.executive_name)
            rows_n = linked
            filename = (filename + " + " if filename else "") + emisiones.name.split("__", 1)[-1]
        rows_n = max(rows_n, ref_n + exec_n)
        summary = {"referidos_dir": ref_n, "ejecutivos_dir": exec_n, "filas_con_vinculo": linked}
        sample = []

    elif profile_id == "cobranza":
        path = _find_staged(token, "file") or _find_staged(token, "pagos")
        if path is None:
            raise ValueError("subí Pagos.xlsx")
        pays = load_pagos_xlsx(path)
        rows_n = len(pays)
        total = sum((p.amount for p in pays), start=_Dec("0"))
        summary = {"pagos": rows_n, "monto_total": str(total)}
        sample = [
            {
                "fila": p.row_number,
                "poliza": p.policy_number or "—",
                "monto": str(p.amount),
                "fecha": str(p.payment_date or "—"),
            }
            for p in pays[:5]
        ]
        filename = path.name.split("__", 1)[-1]
        if any(p.amount <= 0 for p in pays):
            warnings.append("Hay filas con monto ≤ 0 — se omitirán.")

    else:
        raise ValueError("perfil no implementado")

    # persist preview meta
    d = _stage_dir(token)
    (d / "preview.json").write_text(
        json.dumps(
            {
                "profile_id": profile_id,
                "filename": filename,
                "rows": rows_n,
                "summary": summary,
                "warnings": warnings,
                "at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    return PreviewResult(
        profile_id=profile_id,
        token=token,
        filename=filename,
        rows=rows_n,
        summary=summary,
        warnings=warnings,
        sample=sample,
    )


def commit_profile(
    session: Session,
    *,
    profile_id: str,
    token: str,
    organization_id: str,
    actor_id: str,
) -> dict[str, Any]:
    profile = get_profile(profile_id)
    if profile is None:
        raise ValueError("perfil desconocido")

    from corredores.services.materialize_portfolio import materialize_portfolio

    report = ImportReport()

    if profile_id in {"comisiones", "renovaciones"}:
        mat = materialize_portfolio(session, organization_id=organization_id, actor_id=actor_id)
        return {"ok": True, "profile": profile_id, "materialize": mat.as_dict(), "warnings": mat.warnings}

    if profile_id == "clientes":
        path = _find_staged(token, "file") or _find_staged(token, "asegurados")
        if path is None:
            raise ValueError("preview expirado — subí de nuevo")
        parties = load_asegurados_xlsx(path)
        import_parties(session, organization_id=organization_id, rows=parties, report=report)

    elif profile_id == "emisiones":
        path = _find_staged(token, "file") or _find_staged(token, "emisiones")
        if path is None:
            raise ValueError("preview expirado")
        emissions = load_emisiones_xlsx(path)
        import_emissions(
            session, organization_id=organization_id, rows=emissions, actor_id=actor_id, report=report
        )
        link_emission_roles(
            session, organization_id=organization_id, rows=emissions, report=report
        )
        mat = materialize_portfolio(session, organization_id=organization_id, actor_id=actor_id)
        report.materialize = mat.as_dict()
        report.warnings.extend(mat.warnings)

    elif profile_id == "madre":
        pa = _find_staged(token, "asegurados")
        em = _find_staged(token, "emisiones")
        if pa is None or em is None:
            raise ValueError("preview expirado")
        parties = load_asegurados_xlsx(pa)
        emissions = load_emisiones_xlsx(em)
        report = run_assisted_import(
            session, parties=parties, emissions=emissions, actor_id=actor_id
        )
        link_emission_roles(
            session, organization_id=organization_id, rows=emissions, report=report
        )

    elif profile_id == "catalogos":
        path = _find_staged(token, "file") or _find_staged(token, "tablas")
        if path is None:
            raise ValueError("preview expirado")
        cat = load_tablas_xlsx(path)
        import_catalogs(session, organization_id=organization_id, catalogs=cat, report=report)

    elif profile_id == "referidos":
        tablas = _find_staged(token, "tablas") or _find_staged(token, "file")
        emisiones = _find_staged(token, "emisiones")
        if tablas:
            cat = load_tablas_xlsx(tablas)
            import_role_directory(
                session,
                organization_id=organization_id,
                referrers=cat.get("referidos", []),
                executives=cat.get("ejecutivos", []),
                report=report,
            )
        if emisiones:
            em = load_emisiones_xlsx(emisiones)
            link_emission_roles(
                session, organization_id=organization_id, rows=em, report=report
            )

    elif profile_id == "cobranza":
        path = _find_staged(token, "file") or _find_staged(token, "pagos")
        if path is None:
            raise ValueError("preview expirado")
        pays = load_pagos_xlsx(path)
        import_payment_rows(
            session, organization_id=organization_id, rows=pays, actor_id=actor_id, report=report
        )

    else:
        raise ValueError("perfil no implementado")

    session.flush()
    # cleanup staging (best effort)
    try:
        shutil.rmtree(_imports_root() / token, ignore_errors=True)
    except Exception:
        pass

    return {"ok": True, "profile": profile_id, "report": report.as_dict()}
