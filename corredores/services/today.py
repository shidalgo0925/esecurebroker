"""HOY work queue — derived from Domain Truth (not a second ledger)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.enums import PaymentPromiseStatus, RenewalOpportunityStatus
from corredores.domain.models import (
    Installment,
    PaymentPlan,
    PaymentPromise,
    Policy,
    RenewalOpportunity,
)
from corredores.services.collection_bands import classify_collection_band
from corredores.services.installment_status import (
    DerivedInstallmentStatus,
    derive_installment_status,
    outstanding_balance,
)


@dataclass
class WorkItem:
    type: str
    urgency: str
    title: str
    subject_policy_id: str | None
    subject_party_id: str | None
    why: str
    evidence_id: str
    chip: str
    band: str | None = None


def build_today_queue(
    session: Session,
    organization_id: str,
    *,
    today: date | None = None,
    renewal_horizon_days: int = 37,
) -> list[WorkItem]:
    today = today or date.today()
    items: list[WorkItem] = []

    # Collection interventions
    plans = (
        session.query(PaymentPlan)
        .join(Policy, Policy.id == PaymentPlan.policy_id)
        .filter(Policy.organization_id == organization_id)
        .all()
    )
    for plan in plans:
        policy = session.get(Policy, plan.policy_id)
        for inst in plan.installments:
            session.refresh(inst)
            status = derive_installment_status(inst, today)
            bal = outstanding_balance(inst)
            if bal <= 0 or status == DerivedInstallmentStatus.CANCELLED:
                continue
            active = (
                session.query(PaymentPromise)
                .filter_by(
                    organization_id=organization_id,
                    installment_id=inst.id,
                    status=PaymentPromiseStatus.ACTIVE,
                )
                .first()
            )
            broken = (
                session.query(PaymentPromise)
                .filter_by(
                    organization_id=organization_id,
                    installment_id=inst.id,
                    status=PaymentPromiseStatus.BROKEN,
                )
                .order_by(PaymentPromise.updated_at.desc())
                .first()
            )
            band = classify_collection_band(
                inst, active_promise=active, broken_promise=broken, today=today
            )
            if band.value not in ("INTERVENTION", "BROKEN_PROMISE", "PROMISE"):
                # PROMISE still shown on Hoy as soft intervention reminder near date
                if band.value != "PROMISE":
                    continue
            urgency = "CRITICAL" if status == DerivedInstallmentStatus.OVERDUE else "HIGH"
            if status == DerivedInstallmentStatus.OVERDUE:
                chip = "VENCIDO"
            elif status == DerivedInstallmentStatus.DUE:
                chip = "VENCE_HOY"
            elif broken:
                chip = "PROMESA_ROTA"
            elif active:
                chip = "PROMESA_ACTIVA"
            else:
                chip = status.value
            items.append(
                WorkItem(
                    type="COLLECTION",
                    urgency=urgency,
                    title=f"Cuota {inst.installment_number} · saldo {bal}",
                    subject_policy_id=policy.id if policy else plan.policy_id,
                    subject_party_id=policy.client_party_id if policy else None,
                    why=f"due_date={inst.due_date.isoformat()} status={status.value} band={band.value}",
                    evidence_id=inst.id,
                    chip=chip,
                    band=band.value,
                )
            )

    # Renewals in horizon
    horizon = today + timedelta(days=renewal_horizon_days)
    renewals = (
        session.query(RenewalOpportunity)
        .filter_by(organization_id=organization_id)
        .filter(
            RenewalOpportunity.status.in_(
                [
                    RenewalOpportunityStatus.UPCOMING,
                    RenewalOpportunityStatus.CONTACT_PENDING,
                    RenewalOpportunityStatus.CONTACTED,
                    RenewalOpportunityStatus.PROPOSAL_SENT,
                    RenewalOpportunityStatus.WAITING_CLIENT,
                ]
            )
        )
        .all()
    )
    for ren in renewals:
        if ren.target_date and ren.target_date > horizon:
            continue
        items.append(
            WorkItem(
                type="RENEWAL",
                urgency="HIGH" if ren.target_date and ren.target_date <= today + timedelta(days=14) else "NORMAL",
                title=f"Renovación {ren.status}",
                subject_policy_id=ren.previous_policy_id,
                subject_party_id=None,
                why=f"target_date={ren.target_date} status={ren.status}",
                evidence_id=ren.id,
                chip="RENOV_RIESGO",
            )
        )

    # Sort: CRITICAL first, then HIGH, then by type
    order = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2}
    items.sort(key=lambda w: (order.get(w.urgency, 9), w.type, w.title))
    return items
