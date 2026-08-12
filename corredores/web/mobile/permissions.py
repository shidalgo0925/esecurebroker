"""Mobile permissions/entitlements — delegates RBAC shape to access_control (ADR-008 F2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from corredores.services.access_control import (
    SCOPE_ASSIGNED_PORTFOLIO,
    SCOPE_ORGANIZATION,
    SCOPE_PLATFORM,
    permissions_for_role,
)

__all__ = [
    "SCOPE_ORGANIZATION",
    "SCOPE_ASSIGNED_PORTFOLIO",
    "SCOPE_PLATFORM",
    "permissions_for_role",
    "entitlements_payload",
]


def entitlements_payload(session: Session, organization_id: str | None) -> dict[str, Any]:
    """Stable shape for ESB GO. Never invent EN1 commercial truth."""
    from corredores.services.saas_plans import get_plan
    from corredores.services.saas_signup import get_subscription, subscription_allows_access

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
