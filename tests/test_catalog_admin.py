"""Editable master data: carriers, lines, commission rates, split."""

from __future__ import annotations

from decimal import Decimal

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.services.catalog_admin import (
    get_split_for_edit,
    list_line_commission_rates,
    save_all_line_rates,
    save_split_shares,
    upsert_carrier,
    upsert_line,
)
from corredores.services.commission_plan import build_commission_plan_view
from corredores.services.seed_pilot import seed_pilot


def setup_module():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as session:
        seed_pilot(session)
        session.commit()


def _org_id(session):
    from corredores.domain.models import Organization

    org = session.query(Organization).filter_by(name="ESecureBroker").one_or_none()
    if org is None:
        org = session.query(Organization).order_by(Organization.created_at).first()
    assert org is not None
    return org.id


def test_upsert_carrier_and_line():
    with db.SessionLocal() as session:
        org_id = _org_id(session)
        c = upsert_carrier(
            session,
            organization_id=org_id,
            code="test-cia",
            name="Test Cia SA",
            active=True,
            actor_id="t",
        )
        assert c.code == "TEST_CIA"
        l = upsert_line(
            session,
            organization_id=org_id,
            code="nuevo-ramo",
            name="Nuevo Ramo",
            operational_in_p0=True,
            actor_id="t",
        )
        assert l.code == "NUEVO_RAMO"
        session.commit()

    with db.SessionLocal() as session:
        org_id = _org_id(session)
        from corredores.domain.models import Carrier, InsuranceLine

        assert (
            session.query(Carrier)
            .filter_by(organization_id=org_id, code="TEST_CIA")
            .one()
            .name
            == "Test Cia SA"
        )
        assert session.query(InsuranceLine).filter_by(code="NUEVO_RAMO").one().name == "Nuevo Ramo"


def test_save_rates_and_split_visible_in_plan():
    with db.SessionLocal() as session:
        org_id = _org_id(session)
        rows = list_line_commission_rates(session, org_id)
        assert rows
        car = next(r for r in rows if r["code"] == "CAR")
        n = save_all_line_rates(
            session,
            organization_id=org_id,
            rates={car["line_id"]: "22.5"},
            actor_id="t",
        )
        assert n == 1
        save_split_shares(
            session,
            organization_id=org_id,
            broker_pct="50",
            executive_pct="15",
            office_pct="30",
            referral_pct="5",
            actor_id="t",
        )
        session.commit()

    with db.SessionLocal() as session:
        org_id = _org_id(session)
        plan = build_commission_plan_view(session, org_id)
        car = next(r for r in plan.line_rates if r["code"] == "CAR")
        assert car["rate"] == Decimal("0.2250") or car["rate"] == Decimal("0.225")
        assert plan.broker_share == Decimal("0.5000") or plan.broker_share == Decimal("0.5")
        split = get_split_for_edit(session, org_id)
        assert split["broker_pct"] in {"50", "50.0", "50.00"}
