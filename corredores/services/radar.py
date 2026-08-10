"""RADAR aggregates — executive money blocks from Domain Truth / derived status.

Does not duplicate HOY work queue. Returns money + counts for drill-down.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.enums import RenewalOpportunityStatus
from corredores.domain.models import (
    Installment,
    PaymentPlan,
    PaymentPromise,
    Policy,
    RenewalOpportunity,
)
from corredores.domain.enums import PaymentPromiseStatus
from corredores.services.installment_status import (
    DerivedInstallmentStatus,
    derive_installment_status,
    outstanding_balance,
)


@dataclass
class RadarBlock:
    key: str
    label: str
    amount: Decimal
    count: int


@dataclass
class RadarSnapshot:
    as_of: date
    por_cobrar: RadarBlock
    por_renovar: RadarBlock
    por_vender: RadarBlock
    en_riesgo: RadarBlock


def build_radar(
    session: Session,
    organization_id: str,
    *,
    today: date | None = None,
    renewal_horizon_days: int = 90,
) -> RadarSnapshot:
    today = today or date.today()
    horizon = today + timedelta(days=renewal_horizon_days)

    cobrar_amt = Decimal("0")
    cobrar_n = 0
    plans = (
        session.query(PaymentPlan)
        .join(Policy, Policy.id == PaymentPlan.policy_id)
        .filter(Policy.organization_id == organization_id)
        .all()
    )
    overdue_amt = Decimal("0")
    overdue_n = 0
    for plan in plans:
        for inst in plan.installments:
            session.refresh(inst)
            bal = outstanding_balance(inst)
            if bal <= 0:
                continue
            st = derive_installment_status(inst, today)
            if st in (
                DerivedInstallmentStatus.DUE,
                DerivedInstallmentStatus.OVERDUE,
                DerivedInstallmentStatus.PARTIALLY_PAID,
            ):
                cobrar_amt += bal
                cobrar_n += 1
            if st == DerivedInstallmentStatus.OVERDUE:
                overdue_amt += bal
                overdue_n += 1

    renov_amt = Decimal("0")
    renov_n = 0
    renewals = (
        session.query(RenewalOpportunity)
        .filter_by(organization_id=organization_id)
        .filter(
            RenewalOpportunity.status.in_(
                [
                    RenewalOpportunityStatus.UPCOMING,
                    RenewalOpportunityStatus.CONTACT_PENDING,
                    RenewalOpportunityStatus.CONTACTED,
                    RenewalOpportunityStatus.QUOTING,
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
        policy = session.get(Policy, ren.previous_policy_id)
        prima = (policy.annual_premium or policy.net_premium or Decimal("0")) if policy else Decimal("0")
        renov_amt += prima
        renov_n += 1

    # Por vender: open opportunities approximated by broken promises + future gaps placeholder
    # P0: count ACTIVE cross-sell not modeled yet — use OPEN quote-less renewals + zero
    vender_amt = Decimal("0")
    vender_n = 0
    # lightweight: proposals not yet won — renewals in QUOTING count as "por vender" uplift
    for ren in renewals:
        if ren.status == RenewalOpportunityStatus.QUOTING:
            policy = session.get(Policy, ren.previous_policy_id)
            prima = (policy.annual_premium or Decimal("0")) if policy else Decimal("0")
            vender_amt += prima
            vender_n += 1

    broken = (
        session.query(PaymentPromise)
        .filter_by(organization_id=organization_id, status=PaymentPromiseStatus.BROKEN)
        .count()
    )
    riesgo_amt = overdue_amt
    riesgo_n = overdue_n + broken

    return RadarSnapshot(
        as_of=today,
        por_cobrar=RadarBlock("POR_COBRAR", "Dinero por cobrar", cobrar_amt, cobrar_n),
        por_renovar=RadarBlock("POR_RENOVAR", "Dinero por renovar", renov_amt, renov_n),
        por_vender=RadarBlock("POR_VENDER", "Dinero por vender", vender_amt, vender_n),
        en_riesgo=RadarBlock("EN_RIESGO", "Dinero en riesgo", riesgo_amt, riesgo_n),
    )
