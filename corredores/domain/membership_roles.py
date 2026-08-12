"""Canonical org membership role_code values (ADR-008).

F1: recognized constants only — no RBAC enforcement yet.
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

# Default scope mapping (documentation for F2+; not enforced in F1)
DEFAULT_SCOPE_BY_ROLE: dict[str, str] = {
    OWNER: "ORGANIZATION",
    ADMIN: "ORGANIZATION",
    BROKER: "ORGANIZATION",
    COLLECTIONS: "ORGANIZATION",
    PRODUCER: "ASSIGNED_PORTFOLIO",
    PLATFORM: "PLATFORM",
}
