"""ADR-009 — Carrier Incentive Plans F1–F3 (schema + calc + settlement)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.incentive_constants import (
    BASE_COLLECTED_PREMIUM,
    BENEFIT_EARNED,
    BENEFIT_PERCENTAGE,
    METRIC_COLLECTION,
    SETTLE_CLAIMED,
    SETTLE_PAID,
    SETTLE_RECOGNIZED,
    TXN_CONFIRMED,
    TXN_REVERSED,
)
from corredores.domain.models import Carrier, Organization
from corredores.services.carrier_incentives import (
    IncentiveError,
    activate_plan,
    add_tier,
    compute_progress,
    confirm_eligible_txn,
    create_plan,
    mark_claimed,
    mark_paid,
    mark_recognized,
    register_eligible_txn,
    reverse_eligible_txn,
    upsert_calculated_settlement,
)
from corredores.services.seed_pilot import seed_pilot


def setup_module():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as session:
        seed_pilot(session)
        session.commit()


def _org_carrier(session):
    org = session.query(Organization).order_by(Organization.created_at).first()
    assert org is not None
    carrier = session.query(Carrier).filter_by(organization_id=org.id).first()
    assert carrier is not None
    return org, carrier


def test_fianzas_style_goal_200k_2pct():
    with db.SessionLocal() as session:
        org, carrier = _org_carrier(session)
        plan = create_plan(
            session,
            organization_id=org.id,
            carrier_id=carrier.id,
            name="Fianzas 2026",
            metric_type=METRIC_COLLECTION,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            calculation_base=BASE_COLLECTED_PREMIUM,
            actor_id="t",
        )
        add_tier(
            session,
            organization_id=org.id,
            plan_id=plan.id,
            threshold_amount="200000",
            benefit_type=BENEFIT_PERCENTAGE,
            benefit_value="2",
            actor_id="t",
        )
        activate_plan(session, organization_id=org.id, plan_id=plan.id, actor_id="t")
        # Pending does not count officially
        txn = register_eligible_txn(
            session,
            organization_id=org.id,
            plan_id=plan.id,
            amount="167500",
            txn_date=date(2026, 3, 1),
            source_type="MANUAL",
            source_id="p1",
            confirmation_status="PENDING",
        )
        prog = compute_progress(session, organization_id=org.id, plan_id=plan.id)
        assert prog.confirmed_amount == Decimal("0.00")
        assert prog.pending_amount == Decimal("167500.00")

        confirm_eligible_txn(session, organization_id=org.id, txn_id=txn.id)
        register_eligible_txn(
            session,
            organization_id=org.id,
            plan_id=plan.id,
            amount="32500",
            txn_date=date(2026, 6, 1),
            source_type="MANUAL",
            source_id="p2",
            confirmation_status=TXN_CONFIRMED,
        )
        prog = compute_progress(session, organization_id=org.id, plan_id=plan.id)
        assert prog.confirmed_amount == Decimal("200000.00")
        assert prog.benefit_stage == BENEFIT_EARNED
        assert prog.earned_benefit == Decimal("4000.00")
        session.commit()


def test_no_auto_recognized_and_settlement_flow():
    with db.SessionLocal() as session:
        org, carrier = _org_carrier(session)
        plan = create_plan(
            session,
            organization_id=org.id,
            carrier_id=carrier.id,
            name="Plan settle",
            metric_type=METRIC_COLLECTION,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            calculation_base=BASE_COLLECTED_PREMIUM,
        )
        add_tier(
            session,
            organization_id=org.id,
            plan_id=plan.id,
            threshold_amount="1000",
            benefit_type=BENEFIT_PERCENTAGE,
            benefit_value="10",
        )
        activate_plan(session, organization_id=org.id, plan_id=plan.id)
        register_eligible_txn(
            session,
            organization_id=org.id,
            plan_id=plan.id,
            amount="1000",
            txn_date=date(2026, 2, 1),
            source_type="MANUAL",
            source_id="s1",
            confirmation_status=TXN_CONFIRMED,
        )
        s = upsert_calculated_settlement(session, organization_id=org.id, plan_id=plan.id)
        assert s.benefit_stage == BENEFIT_EARNED
        assert s.status != SETTLE_RECOGNIZED
        s = mark_claimed(session, organization_id=org.id, settlement_id=s.id)
        assert s.status == SETTLE_CLAIMED
        s = mark_recognized(
            session,
            organization_id=org.id,
            settlement_id=s.id,
            recognized_amount="95",
        )
        assert s.status == SETTLE_RECOGNIZED
        assert s.closed is True
        s = mark_paid(
            session, organization_id=org.id, settlement_id=s.id, paid_amount="95"
        )
        assert s.status == SETTLE_PAID
        session.commit()


def test_reverse_does_not_delete_and_recalculates():
    with db.SessionLocal() as session:
        org, carrier = _org_carrier(session)
        plan = create_plan(
            session,
            organization_id=org.id,
            carrier_id=carrier.id,
            name="Plan reverse",
            metric_type=METRIC_COLLECTION,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            calculation_base=BASE_COLLECTED_PREMIUM,
        )
        add_tier(
            session,
            organization_id=org.id,
            plan_id=plan.id,
            threshold_amount="500",
            benefit_type="FIXED_AMOUNT",
            benefit_value="50",
        )
        activate_plan(session, organization_id=org.id, plan_id=plan.id)
        txn = register_eligible_txn(
            session,
            organization_id=org.id,
            plan_id=plan.id,
            amount="500",
            txn_date=date(2026, 4, 1),
            source_type="MANUAL",
            source_id="r1",
            confirmation_status=TXN_CONFIRMED,
        )
        prog = compute_progress(session, organization_id=org.id, plan_id=plan.id)
        assert prog.earned_benefit == Decimal("50.00")
        reverse_eligible_txn(
            session, organization_id=org.id, txn_id=txn.id, reason="cancelación cia"
        )
        from corredores.domain.models import CarrierIncentiveEligibleTxn

        still = session.get(CarrierIncentiveEligibleTxn, txn.id)
        assert still is not None
        assert still.confirmation_status == TXN_REVERSED
        prog = compute_progress(session, organization_id=org.id, plan_id=plan.id)
        assert prog.confirmed_amount == Decimal("0.00")
        assert prog.earned_benefit == Decimal("0.00")
        session.commit()


def test_duplicate_source_idempotent():
    with db.SessionLocal() as session:
        org, carrier = _org_carrier(session)
        plan = create_plan(
            session,
            organization_id=org.id,
            carrier_id=carrier.id,
            name="Plan dup",
            metric_type=METRIC_COLLECTION,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            calculation_base=BASE_COLLECTED_PREMIUM,
        )
        add_tier(
            session,
            organization_id=org.id,
            plan_id=plan.id,
            threshold_amount="1",
            benefit_type=BENEFIT_PERCENTAGE,
            benefit_value="1",
        )
        a = register_eligible_txn(
            session,
            organization_id=org.id,
            plan_id=plan.id,
            amount="10",
            txn_date=date(2026, 1, 2),
            source_type="PAYMENT",
            source_id="pay-1",
            confirmation_status=TXN_CONFIRMED,
        )
        b = register_eligible_txn(
            session,
            organization_id=org.id,
            plan_id=plan.id,
            amount="99",
            txn_date=date(2026, 1, 2),
            source_type="PAYMENT",
            source_id="pay-1",
            confirmation_status=TXN_CONFIRMED,
        )
        assert a.id == b.id
        assert b.amount == Decimal("10.00")
        session.commit()
