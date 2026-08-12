"""Regenerate / edit payment plans."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.models import (
    Installment,
    Payment,
    PaymentAllocation,
    PaymentPlan,
    Policy,
)
from corredores.services.auto_e2e import run_auto_e2e_demo
from corredores.services.payment_plan_edit import (
    build_plan_edit_view,
    regenerate_payment_plan,
    update_open_installments,
)


def setup_module():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)


def _clear_payments(session, policy_id: str) -> None:
    plan = session.query(PaymentPlan).filter_by(policy_id=policy_id).one()
    inst_ids = [i.id for i in session.query(Installment).filter_by(payment_plan_id=plan.id)]
    if inst_ids:
        session.query(PaymentAllocation).filter(PaymentAllocation.installment_id.in_(inst_ids)).delete(
            synchronize_session=False
        )
    session.query(Payment).filter_by(policy_id=policy_id).delete(synchronize_session=False)
    session.flush()


def test_regenerate_three_installments():
    with db.SessionLocal() as session:
        result = run_auto_e2e_demo(session, today=date(2026, 1, 15))
        _clear_payments(session, result.policy_id)
        policy = session.get(Policy, result.policy_id)
        assert policy is not None
        regenerate_payment_plan(
            session,
            organization_id=result.organization_id,
            policy_id=policy.id,
            count=3,
            first_due=date(2026, 2, 1),
            actor_id="test",
        )
        view = build_plan_edit_view(session, result.organization_id, policy.id)
        assert view.can_regenerate
        assert len(view.installments) == 3
        total = sum((i["amount"] for i in view.installments), Decimal("0"))
        assert abs(total - view.premium) <= Decimal("0.02")
        assert view.installments[0]["due_date"] == "2026-02-01"
        assert view.installments[1]["due_date"] == "2026-03-01"
        assert view.installments[2]["due_date"] == "2026-04-01"
        session.commit()


def test_cannot_regenerate_after_payment():
    with db.SessionLocal() as session:
        # e2e already records a payment → plan locked
        result = run_auto_e2e_demo(session, org_name="PlanEdit Locked Org", today=date(2026, 1, 15))
        view = build_plan_edit_view(session, result.organization_id, result.policy_id)
        assert not view.can_regenerate
        assert view.locked_count >= 1
        raised = False
        try:
            regenerate_payment_plan(
                session,
                organization_id=result.organization_id,
                policy_id=result.policy_id,
                count=6,
                first_due=date(2026, 3, 1),
            )
        except ValueError:
            raised = True
        assert raised
        session.commit()


def test_update_open_installment_amount():
    with db.SessionLocal() as session:
        result = run_auto_e2e_demo(session, org_name="PlanEdit Update Org", today=date(2026, 1, 15))
        _clear_payments(session, result.policy_id)
        regenerate_payment_plan(
            session,
            organization_id=result.organization_id,
            policy_id=result.policy_id,
            count=2,
            first_due=date(2026, 2, 1),
            actor_id="test",
        )
        view = build_plan_edit_view(session, result.organization_id, result.policy_id)
        a, b = view.installments
        new_a = a["amount"] + Decimal("10.00")
        new_b = b["amount"] - Decimal("10.00")
        update_open_installments(
            session,
            organization_id=result.organization_id,
            policy_id=result.policy_id,
            updates=[
                {"id": a["id"], "due_date": "2026-02-15", "amount": new_a},
                {"id": b["id"], "due_date": b["due_date"], "amount": new_b},
            ],
            actor_id="test",
        )
        view2 = build_plan_edit_view(session, result.organization_id, result.policy_id)
        assert view2.installments[0]["due_date"] == "2026-02-15"
        assert view2.installments[0]["amount"] == new_a
        session.commit()
