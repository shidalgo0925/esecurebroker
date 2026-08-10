"""Cliente 360° read model — aggregates Domain Truth for one party (no UI)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.enums import CoverageKnowledgeState, PaymentPromiseStatus
from corredores.domain.models import (
    Claim,
    Party,
    PartyRole,
    PaymentPlan,
    PaymentPromise,
    Policy,
    RenewalOpportunity,
    Submission,
    VehicleRisk,
)
from corredores.services.installment_status import outstanding_balance


@dataclass
class GapItem:
    risk_kind: str
    label: str
    state: str
    ref_id: str | None = None


@dataclass
class Client360Snapshot:
    party_id: str
    display_name: str
    roles: list[str]
    policies: list[dict]
    vehicles: list[dict]
    submissions: list[dict]
    renewals: list[dict]
    claims: list[dict]
    promises_active: int
    promises_broken: int
    balance_open: Decimal
    gaps: list[GapItem] = field(default_factory=list)


def _party_name(p: Party) -> str:
    if p.party_type == "ORGANIZATION":
        return p.legal_name or p.trade_name or p.id
    parts = [p.first_name or "", p.last_name or ""]
    return " ".join(x for x in parts if x).strip() or p.id


def build_client_360(
    session: Session,
    organization_id: str,
    party_id: str,
    *,
    today: date | None = None,
) -> Client360Snapshot:
    today = today or date.today()
    party = session.get(Party, party_id)
    if party is None or party.organization_id != organization_id:
        raise ValueError("party not found in organization")

    roles = [
        r.role_type
        for r in session.query(PartyRole).filter_by(organization_id=organization_id, party_id=party_id)
    ]
    policies = (
        session.query(Policy)
        .filter_by(organization_id=organization_id, client_party_id=party_id)
        .all()
    )
    policy_ids = [p.id for p in policies]

    vehicles = (
        session.query(VehicleRisk)
        .filter(
            (VehicleRisk.organization_id == organization_id)
            & ((VehicleRisk.policy_id.in_(policy_ids)) if policy_ids else False)
        )
        .all()
        if policy_ids
        else []
    )
    # also vehicles on submissions for this client
    subs = (
        session.query(Submission)
        .filter_by(organization_id=organization_id, client_party_id=party_id)
        .all()
    )
    sub_ids = [s.id for s in subs]
    if sub_ids:
        more_v = (
            session.query(VehicleRisk)
            .filter(VehicleRisk.submission_id.in_(sub_ids))
            .all()
        )
        seen = {v.id for v in vehicles}
        vehicles = list(vehicles) + [v for v in more_v if v.id not in seen]

    renewals = []
    if policy_ids:
        renewals = (
            session.query(RenewalOpportunity)
            .filter(
                RenewalOpportunity.organization_id == organization_id,
                RenewalOpportunity.previous_policy_id.in_(policy_ids),
            )
            .all()
        )

    claims = []
    if policy_ids:
        claims = (
            session.query(Claim)
            .filter(Claim.organization_id == organization_id, Claim.policy_id.in_(policy_ids))
            .all()
        )

    bal = Decimal("0")
    for pol in policies:
        plan = session.query(PaymentPlan).filter_by(policy_id=pol.id).one_or_none()
        if not plan:
            continue
        for inst in plan.installments:
            session.refresh(inst)
            bal += outstanding_balance(inst)

    promises = (
        session.query(PaymentPromise)
        .filter_by(organization_id=organization_id, party_id=party_id)
        .all()
    )
    if not promises and policy_ids:
        promises = (
            session.query(PaymentPromise)
            .filter(
                PaymentPromise.organization_id == organization_id,
                PaymentPromise.policy_id.in_(policy_ids),
            )
            .all()
        )
    active = sum(1 for p in promises if p.status == PaymentPromiseStatus.ACTIVE)
    broken = sum(1 for p in promises if p.status == PaymentPromiseStatus.BROKEN)

    gaps: list[GapItem] = []
    for v in vehicles:
        state = (
            CoverageKnowledgeState.INSURED_WITH_US
            if v.policy_id
            else CoverageKnowledgeState.NO_COVERAGE_RECORDED
        )
        gaps.append(
            GapItem(
                risk_kind="AUTO",
                label=f"{v.make or ''} {v.model or ''} {v.year or ''} {v.plate or ''}".strip(),
                state=state.value,
                ref_id=v.id,
            )
        )
    # Placeholder: unknown other risks not inferred (never "no tiene seguro")
    if not gaps:
        gaps.append(
            GapItem(
                risk_kind="GENERAL",
                label="Sin riesgos vehiculares registrados",
                state=CoverageKnowledgeState.UNKNOWN.value,
            )
        )

    return Client360Snapshot(
        party_id=party.id,
        display_name=_party_name(party),
        roles=roles,
        policies=[
            {
                "id": p.id,
                "number": p.policy_number,
                "status": p.status,
                "premium": str(p.annual_premium or p.net_premium or ""),
            }
            for p in policies
        ],
        vehicles=[
            {
                "id": v.id,
                "make": v.make,
                "model": v.model,
                "year": v.year,
                "plate": v.plate,
                "policy_id": v.policy_id,
            }
            for v in vehicles
        ],
        submissions=[{"id": s.id, "status": s.status} for s in subs],
        renewals=[{"id": r.id, "status": r.status, "target": str(r.target_date)} for r in renewals],
        claims=[{"id": c.id, "status": c.status, "number": c.claim_number} for c in claims],
        promises_active=active,
        promises_broken=broken,
        balance_open=bal,
        gaps=gaps,
    )
