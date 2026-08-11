"""Payment recording — Domain Truth for MONEY."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.enums import DataSource
from corredores.domain.models import AuditEvent, Installment, Payment, PaymentAllocation
from corredores.services.installment_status import outstanding_balance


def record_payment(
    session: Session,
    *,
    organization_id: str,
    policy_id: str,
    amount: Decimal,
    payment_date: date,
    installment_id: str,
    actor_id: str | None = None,
    method: str | None = None,
    reference: str | None = None,
    data_source: str = DataSource.MANUAL,
) -> Payment:
    from corredores.domain.models import PaymentPlan, Policy

    inst = session.get(Installment, installment_id)
    if inst is None:
        raise ValueError("installment not found")
    plan = session.get(PaymentPlan, inst.payment_plan_id)
    if plan is None:
        raise ValueError("payment plan not found")
    policy = session.get(Policy, plan.policy_id)
    if policy is None or policy.organization_id != organization_id:
        raise ValueError("installment not in organization")
    if policy.id != policy_id:
        raise ValueError("installment does not belong to policy")
    bal = outstanding_balance(inst)
    if amount <= 0:
        raise ValueError("amount must be positive")
    if amount > bal + Decimal("0.001"):
        raise ValueError(f"amount {amount} exceeds outstanding balance {bal}")

    payment = Payment(
        organization_id=organization_id,
        policy_id=policy_id,
        amount=amount,
        payment_date=payment_date,
        method=method,
        reference=reference,
        data_source=data_source,
    )
    session.add(payment)
    session.flush()
    session.add(
        PaymentAllocation(payment_id=payment.id, installment_id=installment_id, amount=amount)
    )
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="Payment",
            entity_id=payment.id,
            action="RECORDED",
            detail_json=json.dumps(
                {
                    "installment_id": installment_id,
                    "amount": str(amount),
                    "payment_date": payment_date.isoformat(),
                }
            ),
        )
    )
    session.flush()
    return payment
