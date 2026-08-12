"""F1 schema helpers — ProducerProfile + PortfolioAssignment (ADR-008).

No AccessContext / scope filtering here (F2/F3). Domain integrity only.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from corredores.domain.enums import PartyRoleType, PartyType
from corredores.domain.models import (
    Organization,
    Party,
    PartyRole,
    Policy,
    PortfolioAssignment,
    ProducerProfile,
)


class ProducerPortfolioError(ValueError):
    """Domain validation error for producer/portfolio F1."""


PRODUCER_STATUS_ACTIVE = "ACTIVE"
PRODUCER_STATUS_INACTIVE = "INACTIVE"
PRODUCER_STATUS_ARCHIVED = "ARCHIVED"

TARGET_POLICY = "POLICY"
TARGET_PARTY = "PARTY"
ROLE_PRIMARY = "PRIMARY"
ROLE_SECONDARY = "SECONDARY"  # reserved; not used operationally in P0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_producer_profile(
    session: Session,
    *,
    organization_id: str,
    party_id: str,
    display_name: str | None = None,
    code: str | None = None,
    status: str = PRODUCER_STATUS_ACTIVE,
    sync_agent_party_role: bool = True,
) -> ProducerProfile:
    """
    Create ProducerProfile for a PERSON Party in the same org.

    Membership is NOT required (ADR-008 D-04).

    PartyRole AGENT sync (optional, default on):
      Ensures a GLOBAL PartyRole(role_type=AGENT) for (org, party).
      Does NOT touch EXECUTIVE/REFERRER/CLIENT.
      Does NOT create OrgMembership.
    """
    org = session.get(Organization, organization_id)
    if org is None or not org.active:
        raise ProducerPortfolioError("organization not available")
    party = session.get(Party, party_id)
    if party is None:
        raise ProducerPortfolioError("party not found")
    if party.organization_id != organization_id:
        raise ProducerPortfolioError("party must belong to the same organization")
    if (party.party_type or "").upper() != PartyType.PERSON:
        raise ProducerPortfolioError("producer party must be PERSON")

    name = (display_name or "").strip()
    if not name:
        name = " ".join(
            x for x in [party.first_name or "", party.last_name or ""] if x
        ).strip() or (party.legal_name or party.id)

    code_n = (code or "").strip() or None
    if code_n:
        exists = (
            session.query(ProducerProfile)
            .filter_by(organization_id=organization_id, code=code_n)
            .one_or_none()
        )
        if exists:
            raise ProducerPortfolioError("producer code already in use in organization")

    profile = ProducerProfile(
        organization_id=organization_id,
        party_id=party_id,
        code=code_n,
        display_name=name[:200],
        status=(status or PRODUCER_STATUS_ACTIVE).upper(),
    )
    session.add(profile)
    session.flush()

    if sync_agent_party_role:
        _ensure_agent_global_role(session, organization_id=organization_id, party_id=party_id)

    return profile


def _ensure_agent_global_role(
    session: Session, *, organization_id: str, party_id: str
) -> PartyRole:
    row = (
        session.query(PartyRole)
        .filter_by(
            organization_id=organization_id,
            party_id=party_id,
            role_type=PartyRoleType.AGENT,
            context_type="GLOBAL",
        )
        .filter(PartyRole.context_id.is_(None))
        .one_or_none()
    )
    if row:
        return row
    # UniqueConstraint includes context_id NULL — query may miss duplicates with '' 
    row = PartyRole(
        organization_id=organization_id,
        party_id=party_id,
        role_type=PartyRoleType.AGENT,
        context_type="GLOBAL",
        context_id=None,
    )
    session.add(row)
    session.flush()
    return row


def assign_policy_primary(
    session: Session,
    *,
    organization_id: str,
    producer_profile_id: str,
    policy_id: str,
    effective_from: date | None = None,
    reason: str | None = None,
    assigned_by_subject_id: str | None = None,
    close_existing: bool = True,
) -> PortfolioAssignment:
    """
    Assign PRIMARY producer to a Policy (same org). Closes any current PRIMARY first.

    Enforces one active PRIMARY per policy (DB partial unique + transactional close).
    """
    profile = session.get(ProducerProfile, producer_profile_id)
    if profile is None:
        raise ProducerPortfolioError("producer profile not found")
    if profile.organization_id != organization_id:
        raise ProducerPortfolioError("producer must belong to the organization")

    policy = session.get(Policy, policy_id)
    if policy is None:
        raise ProducerPortfolioError("policy not found")
    if policy.organization_id != organization_id:
        raise ProducerPortfolioError("cross-organization assignment is not allowed")

    today = effective_from or date.today()
    now = _utcnow()

    current = (
        session.query(PortfolioAssignment)
        .filter_by(
            organization_id=organization_id,
            target_type=TARGET_POLICY,
            target_id=policy_id,
            assignment_role=ROLE_PRIMARY,
        )
        .filter(PortfolioAssignment.effective_to.is_(None))
        .one_or_none()
    )
    if current is not None:
        if current.producer_profile_id == producer_profile_id:
            return current
        if not close_existing:
            raise ProducerPortfolioError("policy already has an active PRIMARY assignment")
        current.effective_to = today
        if reason and not current.reason:
            current.reason = f"closed: {reason}"[:500]
        session.flush()

    row = PortfolioAssignment(
        organization_id=organization_id,
        producer_profile_id=producer_profile_id,
        target_type=TARGET_POLICY,
        target_id=policy_id,
        assignment_role=ROLE_PRIMARY,
        effective_from=today,
        effective_to=None,
        reason=(reason or None),
        assigned_by_subject_id=assigned_by_subject_id,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as e:
        raise ProducerPortfolioError(
            "policy already has an active PRIMARY assignment"
        ) from e
    return row


def active_policy_primary(
    session: Session, *, organization_id: str, policy_id: str
) -> PortfolioAssignment | None:
    return (
        session.query(PortfolioAssignment)
        .filter_by(
            organization_id=organization_id,
            target_type=TARGET_POLICY,
            target_id=policy_id,
            assignment_role=ROLE_PRIMARY,
        )
        .filter(PortfolioAssignment.effective_to.is_(None))
        .one_or_none()
    )


def set_default_producer(
    session: Session,
    *,
    organization_id: str,
    party_id: str,
    producer_profile_id: str | None,
) -> Party:
    """Optional Customer default_producer — does NOT assign existing policies."""
    party = session.get(Party, party_id)
    if party is None or party.organization_id != organization_id:
        raise ProducerPortfolioError("party not found in organization")
    if producer_profile_id is not None:
        profile = session.get(ProducerProfile, producer_profile_id)
        if profile is None or profile.organization_id != organization_id:
            raise ProducerPortfolioError("producer profile not found in organization")
    party.default_producer_profile_id = producer_profile_id
    session.flush()
    return party
