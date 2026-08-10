"""Control-plane abstractions (ADR-005 / ADR-006).

P0 may use these without coupling to EN1 implementation.
Do NOT build a definitive identity/subscription system here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Actor:
    """Authenticated principal acting inside Corredores."""

    actor_id: str
    display_name: str | None = None
    email: str | None = None
    en1_subject: str | None = None  # filled when ADR-006 wired


@dataclass(frozen=True)
class OrganizationContext:
    """Tenant context — maps to EN1 organization_id when integrated."""

    organization_id: str
    name: str | None = None
    external_en1_org_id: str | None = None


class EntitlementChecker(Protocol):
    def has(self, organization_id: str, entitlement: str) -> bool: ...


@dataclass
class AllowAllEntitlements:
    """Dev stub until ADR-006. Never use as production identity system."""

    grants: set[str] = field(default_factory=lambda: {"corredores.p0.auto"})

    def has(self, organization_id: str, entitlement: str) -> bool:
        return entitlement in self.grants or "*" in self.grants
