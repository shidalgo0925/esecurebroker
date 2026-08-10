"""CLI helpers for P0 bootstrap."""

from __future__ import annotations

import sys
from pathlib import Path

from corredores.config import settings
from corredores.db import Base, engine
from corredores.domain import models as _models  # noqa: F401


def doctor() -> int:
    print("corredores P0 doctor")
    print(f"  version:     {__import__('corredores').__version__}")
    print(f"  app_env:     {settings.app_env}")
    print(f"  database:    {settings.database_url}")
    Path("/opt/corredores/var").mkdir(parents=True, exist_ok=True)
    # touch metadata
    tables = sorted(Base.metadata.tables.keys())
    print(f"  orm_tables:  {len(tables)}")
    for t in tables:
        print(f"    - {t}")
    return 0


def init_db() -> int:
    Path("/opt/corredores/var").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    print("create_all OK:", settings.database_url)
    return 0


def run_e2e() -> int:
    from corredores.services.auto_e2e import collection_snapshot, run_auto_e2e_demo
    from corredores.db import SessionLocal
    import json

    with SessionLocal() as session:
        result = run_auto_e2e_demo(session)
        snap = collection_snapshot(session, result.policy_id)
    print(json.dumps({"ok": True, "policy_id": result.policy_id, "collection_head": snap[:2]}, indent=2))
    return 0


def today_queue() -> int:
    import json
    from datetime import date

    from corredores.db import SessionLocal
    from corredores.domain.models import Organization
    from corredores.services.today import build_today_queue

    with SessionLocal() as session:
        org = session.query(Organization).order_by(Organization.created_at.desc()).first()
        if org is None:
            print(json.dumps({"ok": False, "error": "no organization — run run-e2e first"}))
            return 1
        items = build_today_queue(session, org.id, today=date.today(), renewal_horizon_days=400)
    print(
        json.dumps(
            {
                "ok": True,
                "organization_id": org.id,
                "count": len(items),
                "items": [
                    {
                        "type": i.type,
                        "urgency": i.urgency,
                        "title": i.title,
                        "chip": i.chip,
                        "band": i.band,
                        "why": i.why,
                    }
                    for i in items[:20]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def radar() -> int:
    import json
    from datetime import date

    from corredores.db import SessionLocal
    from corredores.domain.models import Organization
    from corredores.services.radar import build_radar

    with SessionLocal() as session:
        org = session.query(Organization).order_by(Organization.created_at.desc()).first()
        if org is None:
            print(json.dumps({"ok": False, "error": "no organization — run run-e2e first"}))
            return 1
        snap = build_radar(session, org.id, today=date.today(), renewal_horizon_days=400)
    print(
        json.dumps(
            {
                "ok": True,
                "as_of": snap.as_of.isoformat(),
                "blocks": {
                    b.key: {"label": b.label, "amount": str(b.amount), "count": b.count}
                    for b in (snap.por_cobrar, snap.por_renovar, snap.por_vender, snap.en_riesgo)
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def client360() -> int:
    import json
    from datetime import date

    from corredores.db import SessionLocal
    from corredores.domain.models import Organization, Party
    from corredores.services.client_360 import build_client_360

    with SessionLocal() as session:
        org = session.query(Organization).order_by(Organization.created_at.desc()).first()
        if org is None:
            print(json.dumps({"ok": False, "error": "no organization — run run-e2e first"}))
            return 1
        party = (
            session.query(Party)
            .filter_by(organization_id=org.id)
            .order_by(Party.created_at.desc())
            .first()
        )
        if party is None:
            print(json.dumps({"ok": False, "error": "no party"}))
            return 1
        snap = build_client_360(session, org.id, party.id, today=date.today())
    print(
        json.dumps(
            {
                "ok": True,
                "party_id": snap.party_id,
                "name": snap.display_name,
                "roles": snap.roles,
                "policies": snap.policies,
                "balance_open": str(snap.balance_open),
                "gaps": [{"label": g.label, "state": g.state} for g in snap.gaps],
                "renewals": snap.renewals,
                "claims": snap.claims,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def seed() -> int:
    import json

    from corredores.db import SessionLocal
    from corredores.services.seed_pilot import seed_pilot

    with SessionLocal() as session:
        report = seed_pilot(session)
        session.commit()
    print(json.dumps({"ok": True, **report}, indent=2))
    return 0


def import_excel(argv: list[str]) -> int:
    """Usage: import-excel [--asegurados PATH] [--emisiones PATH]"""
    import json
    from pathlib import Path

    from corredores.db import SessionLocal
    from corredores.services.excel_import import run_assisted_import
    from corredores.services.excel_xlsx import load_workbook_bundle

    asegurados = None
    emisiones = None
    i = 0
    while i < len(argv):
        if argv[i] == "--asegurados" and i + 1 < len(argv):
            asegurados = Path(argv[i + 1])
            i += 2
            continue
        if argv[i] == "--emisiones" and i + 1 < len(argv):
            emisiones = Path(argv[i + 1])
            i += 2
            continue
        print("Usage: import-excel [--asegurados PATH] [--emisiones PATH]")
        return 1
    if not asegurados and not emisiones:
        print("Usage: import-excel [--asegurados PATH] [--emisiones PATH]")
        return 1

    parties, emissions = load_workbook_bundle(asegurados=asegurados, emisiones=emisiones)
    with SessionLocal() as session:
        report = run_assisted_import(session, parties=parties, emissions=emissions)
        session.commit()
    # Report is aggregate counts only — no PII.
    print(json.dumps({"ok": True, **report.as_dict()}, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv or argv[0] in {"doctor", "help"}:
        return doctor()
    if argv[0] == "init-db":
        return init_db()
    if argv[0] == "run-e2e":
        return run_e2e()
    if argv[0] == "today":
        return today_queue()
    if argv[0] == "radar":
        return radar()
    if argv[0] == "client360":
        return client360()
    if argv[0] == "seed":
        return seed()
    if argv[0] == "import-excel":
        return import_excel(argv[1:])
    print(
        "Usage: python -m corredores.cli "
        "[doctor|init-db|run-e2e|today|radar|client360|seed|import-excel]"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
