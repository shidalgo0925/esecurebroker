"""Permissions + entitlements shapes for Mobile API v1 (extensible, not full RBAC)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from corredores.services.saas_plans import get_plan
from corredores.services.saas_signup import get_subscription, subscription_allows_access

# v1 stable capability strings — additive later without breaking clients.
BASE_ORG_PERMISSIONS: tuple[str, ...] = (
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

# Real roles today only.
KNOWN_ROLES = frozenset({"OWNER", "BROKER", "PLATFORM"})

# Documented future (not operational in v1).
FUTURE_ROLES = frozenset({"ADMIN", "PRODUCER", "COLLECTIONS", "SUPERVISOR"})

# Only operational scope in Gate B v1.
SCOPE_ORGANIZATION = "ORGANIZATION"
# Future — not implemented:
# SCOPE_ASSIGNED_PORTFOLIO = "ASSIGNED_PORTFOLIO"


def permissions_for_role(role_code: str, *, is_platform: bool = False) -> list[str]:
    perms = list(BASE_ORG_PERMISSIONS)
    if is_platform or role_code == "PLATFORM":
        perms.append("platform:admin")
    return sorted(set(perms))


def entitlements_payload(session: Session, organization_id: str | None) -> dict[str, Any]:
    """Stable shape for ESB GO. Never invent EN1 commercial truth."""
    if not organization_id:
        return {
            "plan_code": None,
            "entitlements": [],
            "seats": None,
            "source": "pending",
            "subscription_status": None,
        }
    sub = get_subscription(session, organization_id)
    if sub is None:
        return {
            "plan_code": None,
            "entitlements": [],
            "seats": None,
            "source": "pending",
            "subscription_status": None,
        }
    plan = get_plan(sub.plan_code)
    seats = plan.seats_included if plan else None
    if sub.billing_provider == "en1":
        source = "en1"
    elif subscription_allows_access(sub):
        source = "piloto_mirror"
    else:
        source = "pending"
    ents: list[str] = []
    if subscription_allows_access(sub):
        ents.append("esb.access.app")
        ents.append("esb.access.mobile")
        if plan:
            ents.append(f"esb.plan.{plan.code}")
    return {
        "plan_code": sub.plan_code,
        "entitlements": ents,
        "seats": seats,
        "source": source,
        "subscription_status": sub.status,
    }
