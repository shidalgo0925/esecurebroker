"""Claim lifecycle basics — portal hooks via source=BROKER|PORTAL|SYSTEM."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from corredores.domain.enums import ClaimStatus
from corredores.domain.models import AuditEvent, Claim


_ALLOWED = {
    ClaimStatus.REPORTED: {ClaimStatus.DOCUMENTS_PENDING, ClaimStatus.SUBMITTED, ClaimStatus.CLOSED},
    ClaimStatus.DOCUMENTS_PENDING: {ClaimStatus.SUBMITTED, ClaimStatus.REPORTED, ClaimStatus.CLOSED},
    ClaimStatus.SUBMITTED: {ClaimStatus.UNDER_REVIEW, ClaimStatus.CLOSED},
    ClaimStatus.UNDER_REVIEW: {
        ClaimStatus.ADJUSTER_ASSIGNED,
        ClaimStatus.APPROVED,
        ClaimStatus.REJECTED,
        ClaimStatus.CLOSED,
    },
    ClaimStatus.ADJUSTER_ASSIGNED: {
        ClaimStatus.APPROVED,
        ClaimStatus.REJECTED,
        ClaimStatus.UNDER_REVIEW,
    },
    ClaimStatus.APPROVED: {ClaimStatus.SETTLED, ClaimStatus.CLOSED},
    ClaimStatus.REJECTED: {ClaimStatus.CLOSED},
    ClaimStatus.SETTLED: {ClaimStatus.CLOSED},
    ClaimStatus.CLOSED: set(),
}


def open_claim(
    session: Session,
    *,
    organization_id: str,
    policy_id: str,
    party_id: str | None = None,
    loss_date: date | None = None,
    description: str | None = None,
    source: str = "BROKER",
    claim_number: str | None = None,
    actor_id: str | None = None,
) -> Claim:
    claim = Claim(
        organization_id=organization_id,
        policy_id=policy_id,
        party_id=party_id,
        status=ClaimStatus.REPORTED,
        claim_number=claim_number,
        loss_date=loss_date,
        description=description,
        source=source,
        last_activity_at=datetime.now(timezone.utc),
    )
    session.add(claim)
    session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="Claim",
            entity_id=claim.id,
            action="OPENED",
            detail_json=json.dumps({"source": source}),
        )
    )
    session.flush()
    return claim


def advance_claim(
    session: Session,
    claim: Claim,
    new_status: str,
    *,
    actor_id: str | None = None,
) -> Claim:
    allowed = _ALLOWED.get(claim.status, set())
    if new_status not in allowed:
        raise ValueError(f"cannot transition {claim.status} → {new_status}")
    claim.status = new_status
    claim.last_activity_at = datetime.now(timezone.utc)
    session.add(
        AuditEvent(
            organization_id=claim.organization_id,
            actor_id=actor_id,
            entity_type="Claim",
            entity_id=claim.id,
            action=f"STATUS_{new_status}",
            detail_json="{}",
        )
    )
    session.flush()
    return claim
