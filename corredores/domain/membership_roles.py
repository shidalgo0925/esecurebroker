"""Canonical org membership role_code values (ADR-008).

F2: used by access_control.resolve_access_context (role → scope + permissions).
BROKER remains LEGACY / TRANSITIONAL with ORGANIZATION scope (not plan Broker/Red).
PLATFORM is SaaS capability, not a normal brokerage operational role.
"""

from __future__ import annotations

# Operational / transitional roles for OrgMembership.role_code
OWNER = "OWNER"
ADMIN = "ADMIN"
BROKER = "BROKER"  # legacy/transitional internal; scope ORGANIZATION
PRODUCER = "PRODUCER"
COLLECTIONS = "COLLECTIONS"
PLATFORM = "PLATFORM"  # SaaS admin; not normal org catalog

CANONICAL_ROLE_CODES: frozenset[str] = frozenset(
    {OWNER, ADMIN, BROKER, PRODUCER, COLLECTIONS, PLATFORM}
)

DEFAULT_SCOPE_BY_ROLE: dict[str, str] = {
    OWNER: "ORGANIZATION",
    ADMIN: "ORGANIZATION",
    BROKER: "ORGANIZATION",
    COLLECTIONS: "ORGANIZATION",
    PRODUCER: "ASSIGNED_PORTFOLIO",
    PLATFORM: "PLATFORM",
}

# Membership lifecycle (ADR-008 F7) — source of truth; `active` kept in sync for legacy queries
MEMBERSHIP_STATUS_INVITED = "INVITED"
MEMBERSHIP_STATUS_ACTIVE = "ACTIVE"
MEMBERSHIP_STATUS_INACTIVE = "INACTIVE"
MEMBERSHIP_STATUS_REVOKED = "REVOKED"

MEMBERSHIP_STATUSES: frozenset[str] = frozenset(
    {
        MEMBERSHIP_STATUS_INVITED,
        MEMBERSHIP_STATUS_ACTIVE,
        MEMBERSHIP_STATUS_INACTIVE,
        MEMBERSHIP_STATUS_REVOKED,
    }
)

# Seat reservation: INVITED + ACTIVE
MEMBERSHIP_STATUSES_SEAT_HOLD: frozenset[str] = frozenset(
    {MEMBERSHIP_STATUS_INVITED, MEMBERSHIP_STATUS_ACTIVE}
)

# Login / AccessContext
MEMBERSHIP_STATUSES_LOGIN: frozenset[str] = frozenset({MEMBERSHIP_STATUS_ACTIVE})

# Roles assignable by org admin (not PLATFORM)
ORG_ASSIGNABLE_ROLES: frozenset[str] = frozenset(
    {OWNER, ADMIN, BROKER, PRODUCER, COLLECTIONS}
)
