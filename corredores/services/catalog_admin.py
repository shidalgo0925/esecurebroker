"""CRUD de datos maestros (aseguradoras, ramos, % comisiones) — valores en DB."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from corredores.domain.enums import CalculationBase
from corredores.domain.models import (
    AuditEvent,
    Carrier,
    CommissionRule,
    CommissionSplitRule,
    InsuranceLine,
)
from corredores.services.commission_plan import (
    LINE_RATES,
    PLAN_REF,
    SPLIT_REF,
    resolve_active_split_rule,
)


def _norm_code(raw: str) -> str:
    code = re.sub(r"[^A-Z0-9_]+", "", (raw or "").strip().upper().replace(" ", "_").replace("-", "_"))
    return code[:40]


def _pct_to_rate(raw: str) -> Decimal:
    """Accept 20, 20%, 0.20 → Decimal rate 0-1."""
    s = (raw or "").strip().replace("%", "").replace(",", ".")
    if not s:
        raise ValueError("tasa vacía")
    try:
        v = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"tasa inválida: {raw}") from exc
    if v > 1:
        v = v / Decimal("100")
    if v < 0 or v > 1:
        raise ValueError("tasa debe estar entre 0 y 100%")
    return v.quantize(Decimal("0.0001"))


def _share_to_decimal(raw: str) -> Decimal:
    return _pct_to_rate(raw)


# —— Aseguradoras (por org) ——


def list_carriers(session: Session, organization_id: str) -> list[Carrier]:
    return (
        session.query(Carrier)
        .filter_by(organization_id=organization_id)
        .order_by(Carrier.active.desc(), Carrier.name.asc())
        .all()
    )


def upsert_carrier(
    session: Session,
    *,
    organization_id: str,
    code: str,
    name: str,
    active: bool = True,
    carrier_id: str | None = None,
    actor_id: str | None = None,
) -> Carrier:
    code_n = _norm_code(code)
    name_n = (name or "").strip()
    if not code_n:
        raise ValueError("código de aseguradora requerido")
    if not name_n:
        raise ValueError("nombre de aseguradora requerido")
    if carrier_id:
        row = session.get(Carrier, carrier_id)
        if row is None or row.organization_id != organization_id:
            raise ValueError("aseguradora no encontrada")
        # unique code within org
        other = (
            session.query(Carrier)
            .filter_by(organization_id=organization_id, code=code_n)
            .one_or_none()
        )
        if other and other.id != row.id:
            raise ValueError(f"ya existe código {code_n}")
        row.code = code_n
        row.name = name_n[:120]
        row.active = bool(active)
    else:
        existing = (
            session.query(Carrier)
            .filter_by(organization_id=organization_id, code=code_n)
            .one_or_none()
        )
        if existing:
            existing.name = name_n[:120]
            existing.active = bool(active)
            row = existing
        else:
            row = Carrier(
                organization_id=organization_id,
                code=code_n,
                name=name_n[:120],
                active=bool(active),
            )
            session.add(row)
            session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="Carrier",
            entity_id=row.id,
            action="UPSERTED",
            detail_json=f'{{"code":"{row.code}","active":{str(row.active).lower()}}}',
        )
    )
    session.flush()
    return row


# —— Ramos (catálogo global) ——


def list_lines(session: Session) -> list[InsuranceLine]:
    return session.query(InsuranceLine).order_by(InsuranceLine.code.asc()).all()


def upsert_line(
    session: Session,
    *,
    organization_id: str,
    code: str,
    name: str,
    operational_in_p0: bool = False,
    line_id: str | None = None,
    actor_id: str | None = None,
) -> InsuranceLine:
    code_n = _norm_code(code)
    name_n = (name or "").strip()
    if not code_n:
        raise ValueError("código de ramo requerido")
    if not name_n:
        raise ValueError("nombre de ramo requerido")
    if line_id:
        row = session.get(InsuranceLine, line_id)
        if row is None:
            raise ValueError("ramo no encontrado")
        other = session.query(InsuranceLine).filter_by(code=code_n).one_or_none()
        if other and other.id != row.id:
            raise ValueError(f"ya existe ramo {code_n}")
        row.code = code_n
        row.name = name_n[:120]
        row.operational_in_p0 = bool(operational_in_p0)
    else:
        existing = session.query(InsuranceLine).filter_by(code=code_n).one_or_none()
        if existing:
            existing.name = name_n[:120]
            existing.operational_in_p0 = bool(operational_in_p0)
            row = existing
        else:
            row = InsuranceLine(
                code=code_n,
                name=name_n[:120],
                operational_in_p0=bool(operational_in_p0),
            )
            session.add(row)
            session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="InsuranceLine",
            entity_id=row.id,
            action="UPSERTED",
            detail_json=f'{{"code":"{row.code}"}}',
        )
    )
    session.flush()
    return row


# —— % comisión Cia por ramo (por org) ——


def list_line_commission_rates(session: Session, organization_id: str) -> list[dict]:
    lines = list_lines(session)
    rules = (
        session.query(CommissionRule)
        .filter_by(organization_id=organization_id, carrier_id=None)
        .order_by(CommissionRule.valid_from.desc())
        .all()
    )
    by_line: dict[str, CommissionRule] = {}
    for rule in rules:
        if rule.insurance_line_id and rule.insurance_line_id not in by_line:
            by_line[rule.insurance_line_id] = rule
    out = []
    for line in lines:
        rule = by_line.get(line.id)
        rate = rule.rate if rule else LINE_RATES.get(line.code, Decimal("0"))
        out.append(
            {
                "line_id": line.id,
                "code": line.code,
                "name": line.name,
                "rate": rate,
                "rate_pct": f"{(rate * 100):.2f}".rstrip("0").rstrip("."),
                "rule_id": rule.id if rule else None,
                "agreement": (rule.agreement_reference if rule else PLAN_REF),
                "has_rule": rule is not None,
            }
        )
    return out


def upsert_line_commission_rate(
    session: Session,
    *,
    organization_id: str,
    line_id: str,
    rate_pct: str,
    actor_id: str | None = None,
) -> CommissionRule:
    line = session.get(InsuranceLine, line_id)
    if line is None:
        raise ValueError("ramo no encontrado")
    rate = _pct_to_rate(rate_pct)
    rule = (
        session.query(CommissionRule)
        .filter_by(
            organization_id=organization_id,
            insurance_line_id=line.id,
            carrier_id=None,
            agreement_reference=PLAN_REF,
        )
        .one_or_none()
    )
    if rule is None:
        rule = (
            session.query(CommissionRule)
            .filter_by(
                organization_id=organization_id,
                insurance_line_id=line.id,
                carrier_id=None,
            )
            .order_by(CommissionRule.valid_from.desc())
            .first()
        )
    if rule is None:
        rule = CommissionRule(
            organization_id=organization_id,
            carrier_id=None,
            insurance_line_id=line.id,
            rate=rate,
            calculation_base=CalculationBase.ANNUAL_PREMIUM,
            valid_from=date(2020, 1, 1),
            agreement_reference=PLAN_REF,
            source="MANUAL",
        )
        session.add(rule)
    else:
        rule.rate = rate
        rule.agreement_reference = PLAN_REF
        rule.calculation_base = CalculationBase.ANNUAL_PREMIUM
        rule.source = "MANUAL"
    session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="CommissionRule",
            entity_id=rule.id,
            action="UPSERTED",
            detail_json=f'{{"line":"{line.code}","rate":"{rate}"}}',
        )
    )
    session.flush()
    return rule


def save_all_line_rates(
    session: Session,
    *,
    organization_id: str,
    rates: dict[str, str],
    actor_id: str | None = None,
) -> int:
    """rates: line_id → pct string."""
    n = 0
    for line_id, pct in rates.items():
        if not (pct or "").strip():
            continue
        upsert_line_commission_rate(
            session,
            organization_id=organization_id,
            line_id=line_id,
            rate_pct=pct,
            actor_id=actor_id,
        )
        n += 1
    return n


# —— Reparto interno (split) ——


def get_split_for_edit(session: Session, organization_id: str) -> dict:
    split = resolve_active_split_rule(session, organization_id)
    if split is None:
        return {
            "id": None,
            "name": SPLIT_REF,
            "broker_pct": "55",
            "executive_pct": "10",
            "office_pct": "30",
            "referral_pct": "5",
        }
    return {
        "id": split.id,
        "name": split.name,
        "broker_pct": f"{(split.broker_share * 100):.2f}".rstrip("0").rstrip("."),
        "executive_pct": f"{(split.executive_share * 100):.2f}".rstrip("0").rstrip("."),
        "office_pct": f"{(split.office_share * 100):.2f}".rstrip("0").rstrip("."),
        "referral_pct": f"{(split.referral_share * 100):.2f}".rstrip("0").rstrip("."),
    }


def save_split_shares(
    session: Session,
    *,
    organization_id: str,
    broker_pct: str,
    executive_pct: str,
    office_pct: str,
    referral_pct: str,
    name: str | None = None,
    actor_id: str | None = None,
) -> CommissionSplitRule:
    b = _share_to_decimal(broker_pct)
    e = _share_to_decimal(executive_pct)
    o = _share_to_decimal(office_pct)
    r = _share_to_decimal(referral_pct)
    total = b + e + o + r
    if abs(total - Decimal("1")) > Decimal("0.001"):
        raise ValueError(f"el reparto debe sumar 100% (ahora {(total * 100):.2f}%)")
    split = resolve_active_split_rule(session, organization_id)
    if split is None:
        split = CommissionSplitRule(
            organization_id=organization_id,
            name=(name or SPLIT_REF).strip() or SPLIT_REF,
            broker_share=b,
            executive_share=e,
            office_share=o,
            referral_share=r,
            valid_from=date(2020, 1, 1),
        )
        session.add(split)
    else:
        if name and name.strip():
            split.name = name.strip()[:120]
        split.broker_share = b
        split.executive_share = e
        split.office_share = o
        split.referral_share = r
    session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="CommissionSplitRule",
            entity_id=split.id,
            action="UPDATED",
            detail_json=f'{{"broker":"{b}","exec":"{e}","office":"{o}","ref":"{r}"}}',
        )
    )
    session.flush()
    return split
