"""AccessContext — central authz (ADR-008 F2).

ROLE → permissions
SCOPE → data visibility

Web and Mobile MUST use this module. F3 wires Today/list filters; F2 provides
resolve / require_permission / apply_scope / require_entity_in_scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Query, Session

from corredores.domain.membership_roles import (
    ADMIN,
    BROKER,
    COLLECTIONS,
    DEFAULT_SCOPE_BY_ROLE,
    OWNER,
    PLATFORM,
    PRODUCER,
)
from corredores.domain.models import (
    Organization,
    OrgMembership,
    Party,
    Policy,
    PortfolioAssignment,
    ProducerProfile,
)
from corredores.services.producer_portfolio import ROLE_PRIMARY, TARGET_POLICY
from corredores.services.tenant import assert_membership, is_platform_admin, membership_for_org

SCOPE_ORGANIZATION = "ORGANIZATION"
SCOPE_ASSIGNED_PORTFOLIO = "ASSIGNED_PORTFOLIO"
SCOPE_PLATFORM = "PLATFORM"


class AccessDenied(Exception):
    """Permission or scope denial (map to 403/404 at the edge)."""

    def __init__(self, message: str = "forbidden", *, not_found: bool = False):
        super().__init__(message)
        self.not_found = not_found  # True → callers should return 404 (anti-IDOR)


# --- permissions catalog (extensible; not exhaustive ACL) ---

_READ_CORE = (
    "me:read",
    "organizations:list",
    "organizations:select",
    "today:read",
    "customers:list",
    "customers:search",
    "customers:read",
    "customers:360",
    "policies:list",
    "policies:read",
)

_WRITE_CORE = (
    "customers:create",
    "customers:update",
    "policies:create",
    "policies:update",
)

_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    OWNER: _READ_CORE
    + _WRITE_CORE
    + (
        "collections:read",
        "collections:manage",
        "renewals:read",
        "renewals:update",
        "claims:read",
        "claims:update",
        "documents:read",
        "documents:manage",
        "activities:read",
        "activities:create",
        "producers:read",
        "producers:manage",
        "reports:read",
        "settings:manage",
    ),
    ADMIN: _READ_CORE
    + _WRITE_CORE
    + (
        "collections:read",
        "collections:manage",
        "renewals:read",
        "renewals:update",
        "claims:read",
        "claims:update",
        "documents:read",
        "documents:manage",
        "activities:read",
        "activities:create",
        "producers:read",
        "producers:manage",
        "reports:read",
        "settings:manage",
    ),
    BROKER: _READ_CORE
    + _WRITE_CORE
    + (
        "collections:read",
        "renewals:read",
        "renewals:update",
        "claims:read",
        "claims:update",
        "documents:read",
        "documents:manage",
        "activities:read",
        "activities:create",
        "reports:read",
    ),
    COLLECTIONS: _READ_CORE
    + (
        "collections:read",
        "collections:manage",
        "renewals:read",
        "claims:read",
        "documents:read",
        "activities:read",
        "activities:create",
        "reports:read",
    ),
    PRODUCER: _READ_CORE
    + _WRITE_CORE
    + (
        "collections:read",
        "renewals:read",
        "renewals:update",
        "claims:read",
        "claims:update",
        "documents:read",
        "documents:manage",
        "activities:read",
        "activities:create",
        "reports:read",
    ),
    PLATFORM: _READ_CORE
    + (
        "platform:admin",
        "producers:read",
        "reports:read",
        "settings:manage",
    ),
}


@dataclass(frozen=True)
class AccessContext:
    subject_id: str
    username: str
    organization_id: str
    organization: Organization
    membership: OrgMembership | None
    role: str
    scope: str
    permissions: frozenset[str]
    producer_profile_id: str | None = None
    is_platform: bool = False

    def has_permission(self, code: str) -> bool:
        return code in self.permissions


def permissions_for_role(role_code: str, *, is_platform: bool = False) -> list[str]:
    role = (role_code or BROKER).upper()
    base = list(_ROLE_PERMISSIONS.get(role, _ROLE_PERMISSIONS[BROKER]))
    if is_platform or role == PLATFORM:
        if "platform:admin" not in base:
            base.append("platform:admin")
    return sorted(set(base))


def scope_for_role(role_code: str, *, is_platform: bool = False) -> str:
    role = (role_code or BROKER).upper()
    if is_platform and role == PLATFORM:
        return SCOPE_PLATFORM
    return DEFAULT_SCOPE_BY_ROLE.get(role, SCOPE_ORGANIZATION)


def find_producer_profile_for_subject(
    session: Session,
    *,
    organization_id: str,
    subject_id: str,
    username: str,
) -> ProducerProfile | None:
    """Best-effort link Membership → ProducerProfile (F2; no membership.profile_id column yet)."""
    uname = (username or "").strip().lower()
    if uname:
        party = (
            session.query(Party)
            .filter(
                Party.organization_id == organization_id,
                Party.party_type == "PERSON",
                Party.email.isnot(None),
                func.lower(Party.email) == uname,
            )
            .first()
        )
        if party is not None:
            prof = (
                session.query(ProducerProfile)
                .filter_by(organization_id=organization_id, party_id=party.id)
                .one_or_none()
            )
            if prof is not None:
                return prof
    # Single PRODUCER profile in org matching display heuristics — skip (too magic)
    return None


def resolve_access_context(
    session: Session,
    *,
    subject_id: str,
    username: str,
    organization_id: str,
) -> AccessContext:
    org = session.get(Organization, organization_id)
    if org is None or not org.active:
        raise AccessDenied("organization not available")

    is_plat = is_platform_admin(session, subject_id, username=username)
    membership = assert_membership(
        session, subject_id, organization_id, username=username
    )
    if membership is not None:
        role = (membership.role_code or BROKER).upper()
    elif is_plat:
        role = PLATFORM
    else:
        raise AccessDenied("no membership")

    scope = scope_for_role(role, is_platform=is_plat)
    # Platform acting inside an org: operational scope ORGANIZATION for data
    if role == PLATFORM or (is_plat and membership is None):
        scope = SCOPE_ORGANIZATION
        role = PLATFORM if membership is None else role

    perms = frozenset(permissions_for_role(role, is_platform=is_plat))
    producer_id: str | None = None
    if role == PRODUCER:
        prof = find_producer_profile_for_subject(
            session,
            organization_id=organization_id,
            subject_id=subject_id,
            username=username,
        )
        producer_id = prof.id if prof else None

    return AccessContext(
        subject_id=subject_id,
        username=username,
        organization_id=organization_id,
        organization=org,
        membership=membership,
        role=role,
        scope=scope,
        permissions=perms,
        producer_profile_id=producer_id,
        is_platform=is_plat,
    )


def require_permission(ctx: AccessContext, code: str) -> None:
    if not ctx.has_permission(code):
        raise AccessDenied(f"missing permission {code}")


def active_primary_policy_ids(
    session: Session, *, organization_id: str, producer_profile_id: str
) -> set[str]:
    rows = (
        session.query(PortfolioAssignment.target_id)
        .filter_by(
            organization_id=organization_id,
            producer_profile_id=producer_profile_id,
            target_type=TARGET_POLICY,
            assignment_role=ROLE_PRIMARY,
        )
        .filter(PortfolioAssignment.effective_to.is_(None))
        .all()
    )
    return {r[0] for r in rows}


def party_ids_in_portfolio(
    session: Session, *, organization_id: str, policy_ids: Iterable[str]
) -> set[str]:
    """Client parties of the given policies (Policy.client_party_id).

    Canonical P0 \"mis clientes\" for ASSIGNED_PORTFOLIO:
    party with ≥1 PRIMARY-vigente policy in the producer portfolio.
    Does **not** include default_producer-only parties (preassign only).
    """
    ids = list(policy_ids)
    if not ids:
        return set()
    rows = (
        session.query(Policy.client_party_id)
        .filter(
            Policy.organization_id == organization_id,
            Policy.id.in_(ids),
            Policy.client_party_id.isnot(None),
        )
        .distinct()
        .all()
    )
    return {r[0] for r in rows if r[0]}


def visible_portfolio_client_party_ids(
    session: Session, *, organization_id: str, producer_profile_id: str
) -> set[str]:
    """Single allowlist for list / detail / 360 under ASSIGNED_PORTFOLIO."""
    pids = active_primary_policy_ids(
        session,
        organization_id=organization_id,
        producer_profile_id=producer_profile_id,
    )
    return party_ids_in_portfolio(
        session, organization_id=organization_id, policy_ids=pids
    )


def apply_scope_to_policy_query(
    query: Query, session: Session, ctx: AccessContext
) -> Query:
    """Filter a Policy query by AccessContext scope."""
    query = query.filter(Policy.organization_id == ctx.organization_id)
    if ctx.scope == SCOPE_ORGANIZATION or ctx.scope == SCOPE_PLATFORM:
        return query
    if ctx.scope == SCOPE_ASSIGNED_PORTFOLIO:
        if not ctx.producer_profile_id:
            return query.filter(Policy.id.in_([]))  # empty
        pids = active_primary_policy_ids(
            session,
            organization_id=ctx.organization_id,
            producer_profile_id=ctx.producer_profile_id,
        )
        if not pids:
            return query.filter(Policy.id.in_([]))
        return query.filter(Policy.id.in_(pids))
    return query.filter(Policy.id.in_([]))


def apply_scope_to_party_query(
    query: Query, session: Session, ctx: AccessContext
) -> Query:
    query = query.filter(Party.organization_id == ctx.organization_id)
    if ctx.scope in {SCOPE_ORGANIZATION, SCOPE_PLATFORM}:
        return query
    if ctx.scope == SCOPE_ASSIGNED_PORTFOLIO:
        if not ctx.producer_profile_id:
            return query.filter(Party.id.in_([]))
        party_ids = visible_portfolio_client_party_ids(
            session,
            organization_id=ctx.organization_id,
            producer_profile_id=ctx.producer_profile_id,
        )
        if not party_ids:
            return query.filter(Party.id.in_([]))
        return query.filter(Party.id.in_(party_ids))
    return query.filter(Party.id.in_([]))


def require_policy_in_scope(session: Session, ctx: AccessContext, policy_id: str) -> Policy:
    require_permission(ctx, "policies:read")
    pol = session.get(Policy, policy_id)
    if pol is None or pol.organization_id != ctx.organization_id:
        raise AccessDenied("not found", not_found=True)
    if ctx.scope in {SCOPE_ORGANIZATION, SCOPE_PLATFORM}:
        return pol
    if ctx.scope == SCOPE_ASSIGNED_PORTFOLIO:
        if not ctx.producer_profile_id:
            raise AccessDenied("not found", not_found=True)
        pids = active_primary_policy_ids(
            session,
            organization_id=ctx.organization_id,
            producer_profile_id=ctx.producer_profile_id,
        )
        if policy_id not in pids:
            raise AccessDenied("not found", not_found=True)
        return pol
    raise AccessDenied("not found", not_found=True)


def require_party_in_scope(session: Session, ctx: AccessContext, party_id: str) -> Party:
    require_permission(ctx, "customers:read")
    party = session.get(Party, party_id)
    if party is None or party.organization_id != ctx.organization_id:
        raise AccessDenied("not found", not_found=True)
    if ctx.scope in {SCOPE_ORGANIZATION, SCOPE_PLATFORM}:
        return party
    if ctx.scope == SCOPE_ASSIGNED_PORTFOLIO:
        if not ctx.producer_profile_id:
            raise AccessDenied("not found", not_found=True)
        party_ids = visible_portfolio_client_party_ids(
            session,
            organization_id=ctx.organization_id,
            producer_profile_id=ctx.producer_profile_id,
        )
        if party_id not in party_ids:
            raise AccessDenied("not found", not_found=True)
        return party
    raise AccessDenied("not found", not_found=True)


def access_context_public_dict(ctx: AccessContext) -> dict[str, Any]:
    """Stable JSON fragment for /me and debugging."""
    return {
        "role": ctx.role,
        "scope": ctx.scope,
        "permissions": sorted(ctx.permissions),
        "producer_profile_id": ctx.producer_profile_id,
        "organization_id": ctx.organization_id,
        "is_platform": ctx.is_platform,
    }


def scope_allowlists(
    session: Session, ctx: AccessContext
) -> tuple[frozenset[str] | None, frozenset[str] | None]:
    """Return (policy_ids, party_ids) for ASSIGNED_PORTFOLIO.

    ``None`` means unrestricted within the organization (ORGANIZATION / PLATFORM).
    Empty frozenset means scoped but empty portfolio.

    party_ids ≡ clients with ≥1 portfolio PRIMARY policy (same as list/360 gate).
    """
    if ctx.scope in {SCOPE_ORGANIZATION, SCOPE_PLATFORM}:
        return None, None
    if ctx.scope == SCOPE_ASSIGNED_PORTFOLIO:
        if not ctx.producer_profile_id:
            return frozenset(), frozenset()
        pids = frozenset(
            active_primary_policy_ids(
                session,
                organization_id=ctx.organization_id,
                producer_profile_id=ctx.producer_profile_id,
            )
        )
        party_ids = frozenset(
            visible_portfolio_client_party_ids(
                session,
                organization_id=ctx.organization_id,
                producer_profile_id=ctx.producer_profile_id,
            )
        )
        return pids, party_ids
    return frozenset(), frozenset()
