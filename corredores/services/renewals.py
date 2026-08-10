"""Renewal paths — same carrier OR multi-carrier recotización via Quote Orchestrator."""

from __future__ import annotations

import json
from datetime import date
from enum import StrEnum

from sqlalchemy.orm import Session

from corredores.domain.enums import RenewalOpportunityStatus
from corredores.domain.models import AuditEvent, Policy, RenewalOpportunity
from corredores.services.quote_orchestrator import create_quote_request, dispatch_carriers


class RenewalStrategy(StrEnum):
    SAME_CARRIER = "SAME_CARRIER"
    MULTI_CARRIER = "MULTI_CARRIER"


def create_renewal_opportunity(
    session: Session,
    *,
    organization_id: str,
    previous_policy_id: str,
    target_date: date | None = None,
    actor_id: str | None = None,
) -> RenewalOpportunity:
    ren = RenewalOpportunity(
        organization_id=organization_id,
        previous_policy_id=previous_policy_id,
        status=RenewalOpportunityStatus.UPCOMING,
        target_date=target_date,
    )
    session.add(ren)
    session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="RenewalOpportunity",
            entity_id=ren.id,
            action="CREATED",
            detail_json=json.dumps({"previous_policy_id": previous_policy_id}),
        )
    )
    session.flush()
    return ren


def advance_renewal_status(
    session: Session,
    ren: RenewalOpportunity,
    new_status: str,
    *,
    actor_id: str | None = None,
) -> RenewalOpportunity:
    ren.status = new_status
    session.add(
        AuditEvent(
            organization_id=ren.organization_id,
            actor_id=actor_id,
            entity_type="RenewalOpportunity",
            entity_id=ren.id,
            action=f"STATUS_{new_status}",
            detail_json="{}",
        )
    )
    session.flush()
    return ren


def start_same_carrier_renewal(
    session: Session,
    ren: RenewalOpportunity,
    *,
    actor_id: str | None = None,
) -> RenewalOpportunity:
    """Path A — negotiate/renew with current carrier (no multi quote yet)."""
    return advance_renewal_status(
        session, ren, RenewalOpportunityStatus.CONTACTED, actor_id=actor_id
    )


def start_multi_carrier_recote(
    session: Session,
    ren: RenewalOpportunity,
    *,
    carrier_ids: list[str],
    actor_id: str | None = None,
):
    """Path B — open QuoteRequest dispatched to selected carriers."""
    policy = session.get(Policy, ren.previous_policy_id)
    if policy is None:
        raise ValueError("previous policy not found")
    advance_renewal_status(session, ren, RenewalOpportunityStatus.QUOTING, actor_id=actor_id)
    qr = create_quote_request(
        session,
        organization_id=ren.organization_id,
        insurance_line_id=policy.insurance_line_id,
        payload={
            "renewal_opportunity_id": ren.id,
            "previous_policy_id": policy.id,
            "strategy": RenewalStrategy.MULTI_CARRIER.value,
        },
        actor_id=actor_id,
    )
    cqrs = dispatch_carriers(session, qr, carrier_ids, actor_id=actor_id)
    session.add(
        AuditEvent(
            organization_id=ren.organization_id,
            actor_id=actor_id,
            entity_type="RenewalOpportunity",
            entity_id=ren.id,
            action="MULTI_CARRIER_RECOTE",
            detail_json=json.dumps({"quote_request_id": qr.id, "carrier_ids": carrier_ids}),
        )
    )
    session.flush()
    return ren, qr, cqrs


def complete_renewal(
    session: Session,
    ren: RenewalOpportunity,
    *,
    new_policy_id: str,
    actor_id: str | None = None,
) -> RenewalOpportunity:
    ren.new_policy_id = new_policy_id
    return advance_renewal_status(
        session, ren, RenewalOpportunityStatus.RENEWED, actor_id=actor_id
    )
