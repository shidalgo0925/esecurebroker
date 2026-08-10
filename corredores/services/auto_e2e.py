"""P0 AUTO E2E application service — domain backbone only.

No UI, no carrier APIs, no EN1 wiring, no AI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Sequence

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from corredores.domain.enums import (
    CalculationBase,
    DataSource,
    DueDateSource,
    PartyRoleType,
    PartyType,
    PolicyStatus,
    RenewalOpportunityStatus,
    SubmissionStatus,
    TermSource,
)
from corredores.domain.models import (
    AuditEvent,
    Carrier,
    Commission,
    CommissionRule,
    CommissionSplit,
    CommissionSplitRule,
    Installment,
    InsuranceLine,
    Organization,
    Party,
    PartyRole,
    Payment,
    PaymentAllocation,
    PaymentPlan,
    Policy,
    PolicyTerm,
    RenewalOpportunity,
    Submission,
    VehicleRisk,
)
from corredores.services.commission import build_commission
from corredores.services.installment_status import (
    DerivedInstallmentStatus,
    derive_installment_status,
    outstanding_balance,
)


@dataclass
class AutoE2EResult:
    organization_id: str
    client_party_id: str
    submission_id: str
    vehicle_risk_id: str
    policy_id: str
    payment_plan_id: str
    installment_ids: list[str]
    payment_id: str
    commission_id: str
    renewal_id: str
    installment_statuses: dict[str, str]


def _audit(
    session: Session,
    *,
    organization_id: str,
    actor_id: str | None,
    entity_type: str,
    entity_id: str,
    action: str,
    detail: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )


def ensure_auto_line(session: Session) -> InsuranceLine:
    line = session.query(InsuranceLine).filter_by(code="AUTO").one_or_none()
    if line is None:
        line = InsuranceLine(code="AUTO", name="Automóvil", operational_in_p0=True)
        session.add(line)
        session.flush()
    elif not line.operational_in_p0:
        line.operational_in_p0 = True
    return line


def suggest_policy_term(
    effective_date: date,
    *,
    term_source: str = TermSource.SYSTEM_GENERATED,
    expiration_date: date | None = None,
) -> tuple[date, date, str]:
    """D-05: +1 year is historical default suggestion only, not universal truth."""
    if expiration_date is None:
        expiration_date = effective_date + relativedelta(years=1)
        term_source = TermSource.SYSTEM_GENERATED
    return effective_date, expiration_date, term_source


def generate_proposed_installments(
    *,
    start_due: date,
    count: int,
    total_amount: Decimal,
    frequency_months: int = 1,
) -> list[tuple[int, date, Decimal]]:
    """Proposed calendar only — must be confirmable/adjustable (D-01)."""
    if count < 1:
        raise ValueError("count >= 1")
    base = (total_amount / count).quantize(Decimal("0.01"))
    rows: list[tuple[int, date, Decimal]] = []
    allocated = Decimal("0")
    for i in range(1, count + 1):
        due = start_due + relativedelta(months=(i - 1) * frequency_months)
        amount = total_amount - allocated if i == count else base
        allocated += amount
        rows.append((i, due, amount))
    return rows


def run_auto_e2e_demo(
    session: Session,
    *,
    actor_id: str = "p0-system",
    org_name: str = "ESecureBroker",
    today: date | None = None,
) -> AutoE2EResult:
    """Deterministic happy-path for certification of the P0 backbone."""
    today = today or date.today()

    org = session.query(Organization).filter_by(name=org_name).one_or_none()
    if org is None:
        legacy = session.query(Organization).filter_by(name="Piloto Corredores").one_or_none()
        if legacy is not None:
            legacy.name = org_name
            org = legacy
        else:
            org = Organization(name=org_name)
            session.add(org)
            session.flush()

    auto = ensure_auto_line(session)

    carrier = (
        session.query(Carrier)
        .filter_by(organization_id=org.id, code="DEMO")
        .one_or_none()
    )
    if carrier is None:
        carrier = Carrier(organization_id=org.id, code="DEMO", name="Aseguradora Demo")
        session.add(carrier)
        session.flush()

    client = Party(
        organization_id=org.id,
        party_type=PartyType.PERSON,
        first_name="Cliente",
        last_name="Demo",
        national_id="0-000-0000",
        data_source=DataSource.MANUAL,
    )
    session.add(client)
    session.flush()
    session.add(
        PartyRole(
            organization_id=org.id,
            party_id=client.id,
            role_type=PartyRoleType.CLIENT,
            context_type="GLOBAL",
            context_id=None,
        )
    )
    _audit(
        session,
        organization_id=org.id,
        actor_id=actor_id,
        entity_type="Party",
        entity_id=client.id,
        action="CREATED",
    )

    submission = Submission(
        organization_id=org.id,
        client_party_id=client.id,
        carrier_id=carrier.id,
        insurance_line_id=auto.id,
        status=SubmissionStatus.DRAFT,
        data_source=DataSource.MANUAL,
    )
    session.add(submission)
    session.flush()

    vehicle = VehicleRisk(
        organization_id=org.id,
        submission_id=submission.id,
        make="TOYOTA",
        model="HILUX",
        year=2024,
        plate="DEMO001",
        vehicle_type="CAMIONETA",
        usage="PARTICULAR",
    )
    session.add(vehicle)
    session.flush()

    # Advance submission → ISSUED
    for st in (
        SubmissionStatus.QUOTING,
        SubmissionStatus.QUOTED,
        SubmissionStatus.ACCEPTED,
        SubmissionStatus.SUBMITTED,
        SubmissionStatus.ISSUING,
        SubmissionStatus.ISSUED,
    ):
        submission.status = st
        _audit(
            session,
            organization_id=org.id,
            actor_id=actor_id,
            entity_type="Submission",
            entity_id=submission.id,
            action=f"STATUS_{st}",
        )

    net_premium = Decimal("1200.00")
    annual_premium = Decimal("1200.00")
    effective, expiration, term_source = suggest_policy_term(today)

    policy = Policy(
        organization_id=org.id,
        submission_id=submission.id,
        carrier_id=carrier.id,
        insurance_line_id=auto.id,
        policy_number=f"AUTO-DEMO-{today.strftime('%Y%m%d')}",
        status=PolicyStatus.ACTIVE,
        client_party_id=client.id,
        net_premium=net_premium,
        gross_premium=net_premium,
        annual_premium=annual_premium,
        data_source=DataSource.MANUAL,
    )
    session.add(policy)
    session.flush()
    vehicle.policy_id = policy.id

    term = PolicyTerm(
        policy_id=policy.id,
        effective_date=effective,
        expiration_date=expiration,
        term_source=term_source,
    )
    session.add(term)
    session.flush()
    _audit(
        session,
        organization_id=org.id,
        actor_id=actor_id,
        entity_type="Policy",
        entity_id=policy.id,
        action="ISSUED_ACTIVE",
        detail={"term_source": term_source},
    )

    plan = PaymentPlan(policy_id=policy.id, confirmed=False, notes="Calendario propuesto")
    session.add(plan)
    session.flush()

    proposed = generate_proposed_installments(
        start_due=effective, count=12, total_amount=annual_premium, frequency_months=1
    )
    installments: list[Installment] = []
    for num, due, amount in proposed:
        inst = Installment(
            payment_plan_id=plan.id,
            installment_number=num,
            due_date=due,
            amount=amount,
            due_date_source=DueDateSource.SYSTEM_GENERATED,
        )
        session.add(inst)
        installments.append(inst)
    session.flush()
    plan.confirmed = True
    _audit(
        session,
        organization_id=org.id,
        actor_id=actor_id,
        entity_type="PaymentPlan",
        entity_id=plan.id,
        action="CONFIRMED",
        detail={"installments": len(installments)},
    )

    # Pay first installment fully
    first = installments[0]
    payment = Payment(
        organization_id=org.id,
        policy_id=policy.id,
        amount=first.amount,
        payment_date=today,
        method="TRANSFER",
        reference="P0-DEMO-PAY-1",
        data_source=DataSource.MANUAL,
    )
    session.add(payment)
    session.flush()
    session.add(
        PaymentAllocation(payment_id=payment.id, installment_id=first.id, amount=first.amount)
    )
    session.flush()
    # refresh allocations relationship
    session.refresh(first)

    rule = (
        session.query(CommissionRule)
        .filter_by(organization_id=org.id, insurance_line_id=auto.id)
        .one_or_none()
    )
    if rule is None:
        rule = CommissionRule(
            organization_id=org.id,
            carrier_id=carrier.id,
            insurance_line_id=auto.id,
            rate=Decimal("0.20"),
            calculation_base=CalculationBase.NET_PREMIUM,
            valid_from=today,
            agreement_reference="PILOTO-HISTORICO",
            source="MANUAL",
        )
        session.add(rule)
        session.flush()

    split_rule = (
        session.query(CommissionSplitRule)
        .filter_by(organization_id=org.id, name="Default piloto")
        .one_or_none()
    )
    if split_rule is None:
        split_rule = CommissionSplitRule(
            organization_id=org.id,
            name="Default piloto",
            broker_share=Decimal("0.70"),
            office_share=Decimal("0.30"),
            executive_share=Decimal("0"),
            referral_share=Decimal("0"),
            valid_from=today,
        )
        session.add(split_rule)
        session.flush()

    commission = build_commission(organization_id=org.id, policy=policy, rule=rule)
    session.add(commission)
    session.flush()
    session.add(
        CommissionSplit(
            commission_id=commission.id,
            split_rule_id=split_rule.id,
            broker_amount=(commission.calculated_amount * split_rule.broker_share).quantize(Decimal("0.01")),
            office_amount=(commission.calculated_amount * split_rule.office_share).quantize(Decimal("0.01")),
        )
    )
    _audit(
        session,
        organization_id=org.id,
        actor_id=actor_id,
        entity_type="Commission",
        entity_id=commission.id,
        action="CALCULATED",
        detail={
            "calculation_base": commission.calculation_base,
            "base_amount": str(commission.base_amount),
            "rate": str(commission.rate),
            "calculated_amount": str(commission.calculated_amount),
        },
    )

    renewal = RenewalOpportunity(
        organization_id=org.id,
        previous_policy_id=policy.id,
        status=RenewalOpportunityStatus.UPCOMING,
        target_date=expiration,
    )
    session.add(renewal)
    session.flush()
    _audit(
        session,
        organization_id=org.id,
        actor_id=actor_id,
        entity_type="RenewalOpportunity",
        entity_id=renewal.id,
        action="CREATED",
    )

    statuses = {
        inst.id: derive_installment_status(inst, today).value for inst in installments
    }
    # ensure first is PAID
    if statuses[first.id] != DerivedInstallmentStatus.PAID.value:
        raise RuntimeError(f"expected first installment PAID, got {statuses[first.id]}")
    if outstanding_balance(first) != Decimal("0"):
        raise RuntimeError("expected zero balance on first installment")

    session.commit()

    return AutoE2EResult(
        organization_id=org.id,
        client_party_id=client.id,
        submission_id=submission.id,
        vehicle_risk_id=vehicle.id,
        policy_id=policy.id,
        payment_plan_id=plan.id,
        installment_ids=[i.id for i in installments],
        payment_id=payment.id,
        commission_id=commission.id,
        renewal_id=renewal.id,
        installment_statuses=statuses,
    )


def collection_snapshot(
    session: Session, policy_id: str, *, today: date | None = None
) -> list[dict]:
    """Cobranza/morosidad view — derived only (D-19)."""
    today = today or date.today()
    plan = session.query(PaymentPlan).filter_by(policy_id=policy_id).one()
    rows = []
    for inst in sorted(plan.installments, key=lambda x: x.installment_number):
        session.refresh(inst)
        rows.append(
            {
                "installment_number": inst.installment_number,
                "due_date": inst.due_date.isoformat(),
                "amount": str(inst.amount),
                "balance": str(outstanding_balance(inst)),
                "status": derive_installment_status(inst, today).value,
                "due_date_source": inst.due_date_source,
            }
        )
    return rows
