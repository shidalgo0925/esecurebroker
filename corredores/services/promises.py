"""PaymentPromise lifecycle — cobranza Domain Truth."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.enums import PaymentPromiseStatus
from corredores.domain.models import AuditEvent, PaymentPromise


def create_promise(
    session: Session,
    *,
    organization_id: str,
    policy_id: str,
    promised_amount: Decimal,
    promised_date: date,
    installment_id: str | None = None,
    party_id: str | None = None,
    comment: str | None = None,
    actor_id: str | None = None,
) -> PaymentPromise:
    if promised_amount <= 0:
        raise ValueError("promised_amount must be positive")
    promise = PaymentPromise(
        organization_id=organization_id,
        policy_id=policy_id,
        installment_id=installment_id,
        party_id=party_id,
        promised_amount=promised_amount,
        promised_date=promised_date,
        status=PaymentPromiseStatus.ACTIVE,
        comment=comment,
    )
    session.add(promise)
    session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="PaymentPromise",
            entity_id=promise.id,
            action="CREATED",
            detail_json=json.dumps(
                {
                    "promised_date": promised_date.isoformat(),
                    "promised_amount": str(promised_amount),
                }
            ),
        )
    )
    session.flush()
    return promise


def fulfill_promise(
    session: Session, promise: PaymentPromise, *, actor_id: str | None = None
) -> PaymentPromise:
    if promise.status not in (
        PaymentPromiseStatus.ACTIVE,
        PaymentPromiseStatus.BROKEN,
    ):
        raise ValueError(f"cannot fulfill promise in status {promise.status}")
    promise.status = PaymentPromiseStatus.FULFILLED
    promise.resolved_at = datetime.now(timezone.utc)
    session.add(
        AuditEvent(
            organization_id=promise.organization_id,
            actor_id=actor_id,
            entity_type="PaymentPromise",
            entity_id=promise.id,
            action="FULFILLED",
            detail_json="{}",
        )
    )
    session.flush()
    return promise


def fulfill_promises_for_installment(
    session: Session,
    *,
    organization_id: str,
    installment_id: str,
    actor_id: str | None = None,
) -> list[PaymentPromise]:
    """Al registrar un pago, cierra promesas ACTIVE/BROKEN de esa cuota."""
    rows = (
        session.query(PaymentPromise)
        .filter_by(organization_id=organization_id, installment_id=installment_id)
        .filter(
            PaymentPromise.status.in_(
                [PaymentPromiseStatus.ACTIVE, PaymentPromiseStatus.BROKEN]
            )
        )
        .all()
    )
    done: list[PaymentPromise] = []
    for p in rows:
        fulfill_promise(session, p, actor_id=actor_id)
        done.append(p)
    return done


def break_promise(
    session: Session, promise: PaymentPromise, *, actor_id: str | None = None
) -> PaymentPromise:
    if promise.status != PaymentPromiseStatus.ACTIVE:
        raise ValueError(f"cannot break promise in status {promise.status}")
    promise.status = PaymentPromiseStatus.BROKEN
    promise.resolved_at = datetime.now(timezone.utc)
    session.add(
        AuditEvent(
            organization_id=promise.organization_id,
            actor_id=actor_id,
            entity_type="PaymentPromise",
            entity_id=promise.id,
            action="BROKEN",
            detail_json="{}",
        )
    )
    session.flush()
    return promise


def refresh_overdue_promises(
    session: Session, organization_id: str, *, today: date | None = None, actor_id: str | None = None
) -> list[PaymentPromise]:
    """Mark ACTIVE promises past promised_date as BROKEN."""
    today = today or date.today()
    q = (
        session.query(PaymentPromise)
        .filter_by(organization_id=organization_id, status=PaymentPromiseStatus.ACTIVE)
        .filter(PaymentPromise.promised_date < today)
        .all()
    )
    broken: list[PaymentPromise] = []
    for p in q:
        break_promise(session, p, actor_id=actor_id or "system")
        broken.append(p)
    return broken
