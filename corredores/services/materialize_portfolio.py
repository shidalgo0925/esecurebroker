"""Materialize operational portfolio from imported Policies (Emisiones madre).

After Excel import creates Policy + Installments (+ optional Payments), this step
derives what Hoy/Cobranza/Renovaciones/Gestiones need:

- Commission (+ split) from seeded line rules
- RenewalOpportunity at term expiration
- Open Tasks for overdue unpaid installments (gestión de cobro)
- CLIENT PartyRole when missing

Idempotent: skips entities that already exist for the same policy/installment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.enums import (
    DataSource,
    PartyRoleType,
    PolicyStatus,
    RenewalOpportunityStatus,
)
from corredores.domain.models import (
    AuditEvent,
    Commission,
    CommissionRule,
    CommissionSplit,
    CommissionSplitRule,
    Installment,
    Organization,
    PartyRole,
    PaymentPlan,
    Policy,
    PolicyTerm,
    RenewalOpportunity,
    Task,
)
from corredores.services.commission import build_commission
from corredores.services.commission_plan import resolve_active_split_rule
from corredores.services.installment_status import DerivedInstallmentStatus, derive_installment_status
from corredores.services.interactions import create_task, log_interaction
from corredores.services.renewals import create_renewal_opportunity


@dataclass
class MaterializeReport:
    commissions_created: int = 0
    splits_created: int = 0
    renewals_created: int = 0
    collection_tasks_created: int = 0
    client_roles_ensured: int = 0
    interactions_logged: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "commissions_created": self.commissions_created,
            "splits_created": self.splits_created,
            "renewals_created": self.renewals_created,
            "collection_tasks_created": self.collection_tasks_created,
            "client_roles_ensured": self.client_roles_ensured,
            "interactions_logged": self.interactions_logged,
            "warnings": list(self.warnings),
        }


def _ensure_client_role(
    session: Session, *, organization_id: str, party_id: str, report: MaterializeReport
) -> None:
    existing = (
        session.query(PartyRole)
        .filter(
            PartyRole.organization_id == organization_id,
            PartyRole.party_id == party_id,
            PartyRole.role_type == PartyRoleType.CLIENT,
            PartyRole.context_type == "GLOBAL",
        )
        .first()
    )
    if existing is None:
        session.add(
            PartyRole(
                organization_id=organization_id,
                party_id=party_id,
                role_type=PartyRoleType.CLIENT,
                context_type="GLOBAL",
                context_id=None,
            )
        )
        report.client_roles_ensured += 1


def _pick_commission_rule(
    session: Session, *, organization_id: str, policy: Policy
) -> CommissionRule | None:
    q = (
        session.query(CommissionRule)
        .filter_by(organization_id=organization_id, insurance_line_id=policy.insurance_line_id)
        .order_by(CommissionRule.valid_from.desc())
    )
    rules = q.all()
    if not rules:
        return None
    # Prefer carrier-specific, else org-wide (carrier_id NULL).
    for rule in rules:
        if rule.carrier_id == policy.carrier_id:
            return rule
    for rule in rules:
        if rule.carrier_id is None:
            return rule
    return rules[0]


def materialize_portfolio(
    session: Session,
    *,
    organization_id: str | None = None,
    org_name: str = "ESecureBroker",
    today: date | None = None,
    actor_id: str = "portfolio-materialize",
    renewal_horizon_days: int = 120,
) -> MaterializeReport:
    """Derive commissions, renewals, and collection gestiones from Policies."""
    report = MaterializeReport()
    today = today or date.today()

    if organization_id is None:
        org = session.query(Organization).filter_by(name=org_name).one_or_none()
        if org is None:
            report.warnings.append("organization not found")
            return report
        organization_id = org.id

    split_rule = resolve_active_split_rule(session, organization_id)

    policies = (
        session.query(Policy)
        .filter_by(organization_id=organization_id)
        .filter(Policy.status == PolicyStatus.ACTIVE)
        .all()
    )

    for policy in policies:
        _ensure_client_role(
            session, organization_id=organization_id, party_id=policy.client_party_id, report=report
        )

        # —— Commission ——
        existing_comm = (
            session.query(Commission).filter_by(policy_id=policy.id).first()
        )
        if existing_comm is None:
            rule = _pick_commission_rule(
                session, organization_id=organization_id, policy=policy
            )
            if rule is None:
                report.warnings.append(f"policy {policy.policy_number or policy.id[:8]}: no commission rule")
            else:
                # Emisiones often fills Prima but leaves Prima Anual empty on riders.
                fallback_base = (
                    policy.annual_premium or policy.gross_premium or policy.net_premium
                )
                try:
                    if fallback_base is not None:
                        commission = build_commission(
                            organization_id=organization_id,
                            policy=policy,
                            rule=rule,
                            base_amount=Decimal(fallback_base),
                        )
                    else:
                        commission = build_commission(
                            organization_id=organization_id, policy=policy, rule=rule
                        )
                except ValueError as exc:
                    report.warnings.append(
                        f"policy {policy.policy_number or policy.id[:8]}: commission skipped ({exc})"
                    )
                else:
                    session.add(commission)
                    session.flush()
                    report.commissions_created += 1
                    session.add(
                        AuditEvent(
                            organization_id=organization_id,
                            actor_id=actor_id,
                            entity_type="Commission",
                            entity_id=commission.id,
                            action="CALCULATED",
                            detail_json="{}",
                        )
                    )
                    if split_rule is not None:
                        session.add(
                            CommissionSplit(
                                commission_id=commission.id,
                                split_rule_id=split_rule.id,
                                broker_amount=(
                                    commission.calculated_amount * split_rule.broker_share
                                ).quantize(Decimal("0.01")),
                                office_amount=(
                                    commission.calculated_amount * split_rule.office_share
                                ).quantize(Decimal("0.01")),
                                executive_amount=(
                                    commission.calculated_amount * split_rule.executive_share
                                ).quantize(Decimal("0.01")),
                                referral_amount=(
                                    commission.calculated_amount * split_rule.referral_share
                                ).quantize(Decimal("0.01")),
                            )
                        )
                        report.splits_created += 1

        # —— Renewal ——
        existing_ren = (
            session.query(RenewalOpportunity)
            .filter_by(organization_id=organization_id, previous_policy_id=policy.id)
            .filter(
                RenewalOpportunity.status.in_(
                    [
                        RenewalOpportunityStatus.UPCOMING,
                        RenewalOpportunityStatus.CONTACT_PENDING,
                        RenewalOpportunityStatus.CONTACTED,
                        RenewalOpportunityStatus.PROPOSAL_SENT,
                        RenewalOpportunityStatus.WAITING_CLIENT,
                        RenewalOpportunityStatus.QUOTING,
                    ]
                )
            )
            .first()
        )
        if existing_ren is None:
            term = session.query(PolicyTerm).filter_by(policy_id=policy.id).first()
            target = term.expiration_date if term else None
            # Always create so renovaciones board has the full cartera; Hoy filters by horizon.
            create_renewal_opportunity(
                session,
                organization_id=organization_id,
                previous_policy_id=policy.id,
                target_date=target,
                actor_id=actor_id,
            )
            report.renewals_created += 1
            _ = renewal_horizon_days

        # —— Cobranza gestiones (overdue unpaid installments) ——
        plan = session.query(PaymentPlan).filter_by(policy_id=policy.id).first()
        if plan is None:
            continue
        installments = (
            session.query(Installment)
            .filter_by(payment_plan_id=plan.id)
            .order_by(Installment.installment_number)
            .all()
        )
        for inst in installments:
            derived = derive_installment_status(inst, today)
            if derived != DerivedInstallmentStatus.OVERDUE:
                continue
            existing_task = (
                session.query(Task)
                .filter_by(
                    organization_id=organization_id,
                    policy_id=policy.id,
                    related_type="INSTALLMENT",
                    related_id=inst.id,
                    status="OPEN",
                )
                .first()
            )
            if existing_task is not None:
                continue
            days = (today - inst.due_date).days
            create_task(
                session,
                organization_id=organization_id,
                title=f"Cobro cuota {inst.installment_number} vencida ({days}d)",
                due_date=today,
                party_id=policy.client_party_id,
                policy_id=policy.id,
                related_type="INSTALLMENT",
                related_id=inst.id,
                actor_id=actor_id,
            )
            log_interaction(
                session,
                organization_id=organization_id,
                summary=(
                    f"Gestión de cobro abierta · cuota {inst.installment_number} "
                    f"vencida hace {days} días · monto {inst.amount}"
                ),
                channel="SYSTEM",
                party_id=policy.client_party_id,
                policy_id=policy.id,
                actor_id=actor_id,
                data_source=DataSource.SYSTEM_GENERATED,
            )
            report.collection_tasks_created += 1
            report.interactions_logged += 1

    session.flush()
    return report
