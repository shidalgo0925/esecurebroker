"""Edit / regenerate PaymentPlan installments (Domain Truth facts).

Rules:
- Installments with allocations (pagos aplicados) are locked.
- Regenerating replaces only unlocked installments; if any paid, refuse full regen.
- Amounts must sum to the policy premium when regenerating the whole plan.
- Policy premium may be corrected only when the policy has no payment transactions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from corredores.domain.enums import DueDateSource
from corredores.domain.models import (
    AuditEvent,
    Installment,
    Payment,
    PaymentAllocation,
    PaymentPlan,
    PaymentPromise,
    Policy,
    PolicyTerm,
    Task,
)
from corredores.services.auto_e2e import generate_proposed_installments
from corredores.services.installment_status import allocated_total
from corredores.services.materialize_portfolio import materialize_portfolio


@dataclass
class PlanEditView:
    policy_id: str
    policy_number: str
    premium: Decimal
    net_premium: Decimal | None
    gross_premium: Decimal | None
    effective_date: date | None
    plan_id: str | None
    confirmed: bool
    notes: str
    installments: list[dict]
    locked_count: int
    payment_count: int
    can_regenerate: bool
    can_edit_premium: bool


def _premium(policy: Policy) -> Decimal:
    for v in (policy.annual_premium, policy.gross_premium, policy.net_premium):
        if v is not None and Decimal(str(v)) > 0:
            return Decimal(str(v))
    return Decimal("0")


def _parse_money(value: str | Decimal | None, *, field: str) -> Decimal:
    if value is None or str(value).strip() == "":
        raise ValueError(f"{field} requerida")
    try:
        amt = Decimal(str(value).replace(",", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} inválida") from exc
    if amt <= 0:
        raise ValueError(f"{field} debe ser > 0")
    return amt


def _is_locked(session: Session, installment: Installment) -> bool:
    if allocated_total(installment) > 0:
        return True
    n = session.query(PaymentAllocation).filter_by(installment_id=installment.id).count()
    return n > 0


def _payment_count(session: Session, policy_id: str) -> int:
    return session.query(Payment).filter_by(policy_id=policy_id).count()


def build_plan_edit_view(session: Session, organization_id: str, policy_id: str) -> PlanEditView:
    policy = session.get(Policy, policy_id)
    if policy is None or policy.organization_id != organization_id:
        raise ValueError("póliza no encontrada")
    term = session.query(PolicyTerm).filter_by(policy_id=policy.id).first()
    plan = session.query(PaymentPlan).filter_by(policy_id=policy.id).first()
    rows: list[dict] = []
    locked = 0
    if plan:
        insts = (
            session.query(Installment)
            .filter_by(payment_plan_id=plan.id)
            .order_by(Installment.installment_number)
            .all()
        )
        for i in insts:
            lock = _is_locked(session, i)
            if lock:
                locked += 1
            paid = allocated_total(i)
            rows.append(
                {
                    "id": i.id,
                    "number": i.installment_number,
                    "due_date": i.due_date.isoformat(),
                    "amount": i.amount,
                    "paid": paid,
                    "balance": i.amount - paid,
                    "locked": lock,
                }
            )
    premium = _premium(policy)
    payments = _payment_count(session, policy.id)
    can_edit_premium = locked == 0 and payments == 0
    return PlanEditView(
        policy_id=policy.id,
        policy_number=policy.policy_number or policy.id[:8],
        premium=premium,
        net_premium=policy.net_premium,
        gross_premium=policy.gross_premium,
        effective_date=term.effective_date if term else None,
        plan_id=plan.id if plan else None,
        confirmed=bool(plan and plan.confirmed),
        notes=(plan.notes or "") if plan else "",
        installments=rows,
        locked_count=locked,
        payment_count=payments,
        can_regenerate=(locked == 0 and premium > 0),
        can_edit_premium=can_edit_premium,
    )


def _rescale_installments_to_premium(
    session: Session, *, plan: PaymentPlan, premium: Decimal
) -> None:
    insts = (
        session.query(Installment)
        .filter_by(payment_plan_id=plan.id)
        .order_by(Installment.installment_number)
        .all()
    )
    if not insts:
        return
    for i in insts:
        if _is_locked(session, i):
            raise ValueError("no se puede repartir: hay cuotas con pagos aplicados")
    n = len(insts)
    base = (premium / n).quantize(Decimal("0.01"))
    amounts = [base] * n
    diff = premium - sum(amounts)
    amounts[-1] = (amounts[-1] + diff).quantize(Decimal("0.01"))
    for i, amt in zip(insts, amounts):
        if amt <= 0:
            raise ValueError("prima demasiado baja para el número de cuotas")
        i.amount = amt


def update_policy_premium(
    session: Session,
    *,
    organization_id: str,
    policy_id: str,
    annual_premium: str | Decimal,
    net_premium: str | Decimal | None = None,
    gross_premium: str | Decimal | None = None,
    actor_id: str | None = None,
    rescale_installments: bool = True,
) -> Policy:
    """Correct policy premium when there are no payment transactions."""
    view = build_plan_edit_view(session, organization_id, policy_id)
    if not view.can_edit_premium:
        raise ValueError(
            "no se puede editar la prima: la póliza tiene transacciones (pagos aplicados)"
        )
    policy = session.get(Policy, policy_id)
    assert policy is not None

    annual = _parse_money(annual_premium, field="prima anual")
    net = (
        _parse_money(net_premium, field="prima neta")
        if net_premium is not None and str(net_premium).strip() != ""
        else annual
    )
    gross: Decimal | None = None
    if gross_premium is not None and str(gross_premium).strip() != "":
        gross = _parse_money(gross_premium, field="prima bruta")

    old = {
        "annual": str(policy.annual_premium) if policy.annual_premium is not None else None,
        "net": str(policy.net_premium) if policy.net_premium is not None else None,
        "gross": str(policy.gross_premium) if policy.gross_premium is not None else None,
    }
    policy.annual_premium = annual
    policy.net_premium = net
    if gross is not None:
        policy.gross_premium = gross

    plan = session.query(PaymentPlan).filter_by(policy_id=policy.id).first()
    rescaled = bool(rescale_installments and plan is not None and view.installments)
    if rescaled:
        _rescale_installments_to_premium(session, plan=plan, premium=annual)

    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="Policy",
            entity_id=policy.id,
            action="PREMIUM_CORRECTED",
            detail_json=json.dumps(
                {
                    "old": old,
                    "new": {
                        "annual": str(annual),
                        "net": str(net),
                        "gross": str(gross) if gross is not None else None,
                    },
                    "rescaled_installments": rescaled,
                }
            ),
        )
    )
    session.flush()
    materialize_portfolio(session, organization_id=organization_id, actor_id=actor_id or "premium-edit")
    return policy


def regenerate_payment_plan(
    session: Session,
    *,
    organization_id: str,
    policy_id: str,
    count: int,
    first_due: date | None = None,
    frequency_months: int = 1,
    actor_id: str | None = None,
    confirm: bool = True,
) -> PaymentPlan:
    if count < 1 or count > 60:
        raise ValueError("número de cuotas debe estar entre 1 y 60")
    if frequency_months < 1 or frequency_months > 12:
        raise ValueError("frecuencia inválida")

    view = build_plan_edit_view(session, organization_id, policy_id)
    if not view.can_regenerate:
        raise ValueError(
            "no se puede regenerar: hay cuotas con pagos aplicados — editá solo las abiertas"
        )
    policy = session.get(Policy, policy_id)
    assert policy is not None
    premium = view.premium
    if premium <= 0:
        raise ValueError("la póliza no tiene prima para repartir")

    start = first_due or view.effective_date or date.today()
    plan = session.query(PaymentPlan).filter_by(policy_id=policy.id).first()
    if plan is None:
        plan = PaymentPlan(policy_id=policy.id, confirmed=confirm, notes="")
        session.add(plan)
        session.flush()

    # Clear open tasks / promises tied to old installments (no allocations at this point)
    old = session.query(Installment).filter_by(payment_plan_id=plan.id).all()
    old_ids = [i.id for i in old]
    if old_ids:
        session.query(PaymentPromise).filter(PaymentPromise.installment_id.in_(old_ids)).delete(
            synchronize_session=False
        )
        session.query(Task).filter(Task.policy_id == policy.id).filter(
            Task.title.ilike("%cuota%")
        ).delete(synchronize_session=False)
        for i in old:
            session.delete(i)
        session.flush()

    for num, due, amt in generate_proposed_installments(
        start_due=start,
        count=count,
        total_amount=premium,
        frequency_months=frequency_months,
    ):
        session.add(
            Installment(
                payment_plan_id=plan.id,
                installment_number=num,
                due_date=due,
                amount=amt,
                due_date_source=DueDateSource.MANUAL,
            )
        )
    plan.confirmed = confirm
    tag = f"{count} CUOTA{'S' if count != 1 else ''}"
    base_notes = (plan.notes or "").strip()
    # refresh cuota tag in notes
    parts = [p for p in base_notes.split(" · ") if p and "CUOTA" not in p.upper() and p.upper() != "CONTADO"]
    parts.append(tag)
    plan.notes = " · ".join(parts)

    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="PaymentPlan",
            entity_id=plan.id,
            action="REGENERATED",
            detail_json=f'{{"policy_id":"{policy.id}","count":{count},"first_due":"{start.isoformat()}"}}',
        )
    )
    session.flush()
    materialize_portfolio(session, organization_id=organization_id, actor_id=actor_id or "plan-edit")
    return plan


def update_open_installments(
    session: Session,
    *,
    organization_id: str,
    policy_id: str,
    updates: list[dict],
    actor_id: str | None = None,
) -> PaymentPlan:
    """Patch due_date/amount on unlocked installments. Sum of all amounts must match premium."""
    policy = session.get(Policy, policy_id)
    if policy is None or policy.organization_id != organization_id:
        raise ValueError("póliza no encontrada")
    plan = session.query(PaymentPlan).filter_by(policy_id=policy.id).first()
    if plan is None:
        raise ValueError("sin plan de pagos")
    premium = _premium(policy)
    by_id = {u["id"]: u for u in updates if u.get("id")}

    insts = (
        session.query(Installment)
        .filter_by(payment_plan_id=plan.id)
        .order_by(Installment.installment_number)
        .all()
    )
    total = Decimal("0")
    for i in insts:
        if i.id in by_id and not _is_locked(session, i):
            u = by_id[i.id]
            if u.get("due_date"):
                i.due_date = u["due_date"] if isinstance(u["due_date"], date) else date.fromisoformat(str(u["due_date"]))
                i.due_date_source = DueDateSource.MANUAL
            if u.get("amount") is not None:
                try:
                    amt = Decimal(str(u["amount"]).replace(",", "")).quantize(Decimal("0.01"))
                except (InvalidOperation, ValueError) as exc:
                    raise ValueError(f"monto inválido en cuota {i.installment_number}") from exc
                if amt <= 0:
                    raise ValueError(f"monto debe ser > 0 en cuota {i.installment_number}")
                paid = allocated_total(i)
                if amt < paid:
                    raise ValueError(
                        f"cuota {i.installment_number}: monto {amt} < pagado {paid}"
                    )
                i.amount = amt
        total += i.amount

    if premium > 0 and abs(total - premium) > Decimal("0.02"):
        raise ValueError(f"la suma de cuotas ({total}) debe igualar la prima ({premium})")

    plan.confirmed = True
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="PaymentPlan",
            entity_id=plan.id,
            action="UPDATED_INSTALLMENTS",
            detail_json=f'{{"policy_id":"{policy.id}","count":{len(insts)}}}',
        )
    )
    session.flush()
    materialize_portfolio(session, organization_id=organization_id, actor_id=actor_id or "plan-edit")
    return plan
