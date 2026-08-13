"""ADR-008 F5 — Seat limits (EN1 SoR when present; ESB enforces on access activation).

EN1 may supply ``limits.internal_seats`` / ``limits.producer_seats`` on entitlement.
Until CODITO freezes the compound shape, ESB:
  - prefers persisted EN1 limits on OrgSubscription
  - else plan-catalog mirror (piloto_mirror) — never invents EN1 live values
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from corredores.domain.membership_roles import (
    BROKER,
    MEMBERSHIP_STATUS_ACTIVE,
    MEMBERSHIP_STATUSES_SEAT_HOLD,
    PLATFORM,
    PRODUCER,
)
from corredores.domain.models import OrgMembership, OrgSubscription, ProducerProfile
from corredores.services.producer_portfolio import PRODUCER_STATUS_ACTIVE
from corredores.services.saas_plans import get_plan
from corredores.services.saas_signup import get_subscription


def _membership_holds_seat(m: OrgMembership) -> bool:
    status = (getattr(m, "status", None) or "").upper()
    if status:
        return status in MEMBERSHIP_STATUSES_SEAT_HOLD
    return bool(m.active)


class SeatLimitError(ValueError):
    """Seat quota exceeded or invalid seat operation."""


@dataclass(frozen=True)
class SeatBucket:
    limit: int | None  # None = unlimited / a medida
    used: int

    @property
    def remaining(self) -> int | None:
        if self.limit is None:
            return None
        return max(0, self.limit - self.used)

    @property
    def available(self) -> bool:
        if self.limit is None:
            return True
        return self.used < self.limit


@dataclass(frozen=True)
class SeatSnapshot:
    organization_id: str
    plan_code: str | None
    source: str  # en1 | plan_catalog | pending
    internal: SeatBucket
    producer: SeatBucket

    def public_dict(self) -> dict[str, Any]:
        return {
            "internal_seats": {
                "limit": self.internal.limit,
                "used": self.internal.used,
                "remaining": self.internal.remaining,
            },
            "producer_seats": {
                "limit": self.producer.limit,
                "used": self.producer.used,
                "remaining": self.producer.remaining,
            },
            "source": self.source,
            "plan_code": self.plan_code,
        }


def _plan_catalog_limits(plan_code: str | None) -> tuple[int | None, int | None]:
    """Mirror defaults from PLANES_COMERCIALES_V1 until EN1 compound seats land."""
    plan = get_plan(plan_code or "")
    if plan is None:
        return None, None
    code = plan.code
    internal = plan.seats_included  # None for enterprise
    if code == "individual":
        return 1, 0
    if code == "oficina":
        return 15, 0
    if code == "broker_red":
        # Internal office seats; producers aparte — unlimited until EN1 says otherwise
        return 15, None
    if code == "enterprise":
        return None, None
    return internal, 0


def extract_en1_seat_limits(limits: dict[str, Any] | None) -> tuple[int | None, int | None] | None:
    """Parse EN1 entitlement.limits when compound keys exist. None = not provided."""
    if not limits or not isinstance(limits, dict):
        return None
    if "internal_seats" not in limits and "producer_seats" not in limits:
        # legacy single key?
        if "seats" in limits and isinstance(limits["seats"], int):
            return int(limits["seats"]), 0
        return None

    def _as_opt_int(v: Any) -> int | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
        return None

    return _as_opt_int(limits.get("internal_seats")), _as_opt_int(limits.get("producer_seats"))


def persist_en1_seat_limits(
    session: Session, sub: OrgSubscription, limits: dict[str, Any] | None
) -> None:
    parsed = extract_en1_seat_limits(limits)
    if parsed is None:
        return
    internal, producer = parsed
    sub.internal_seats_limit = internal
    sub.producer_seats_limit = producer
    sub.seats_limits_source = "en1"
    session.flush()


def count_internal_seats_used(session: Session, organization_id: str) -> int:
    """ACTIVE + INVITED non-producer memberships (F7 seat reservation)."""
    rows = session.query(OrgMembership).filter_by(organization_id=organization_id).all()
    n = 0
    for m in rows:
        if not _membership_holds_seat(m):
            continue
        role = (m.role_code or BROKER).upper()
        if role in {PRODUCER, PLATFORM}:
            continue
        n += 1
    return n


def count_producer_seats_used(session: Session, organization_id: str) -> int:
    """ACTIVE + INVITED PRODUCER memberships. Profile-only does not count."""
    rows = (
        session.query(OrgMembership)
        .filter_by(organization_id=organization_id, role_code=PRODUCER)
        .all()
    )
    return sum(1 for m in rows if _membership_holds_seat(m))


def resolve_seat_limits(
    session: Session, organization_id: str
) -> tuple[int | None, int | None, str, str | None]:
    """Return (internal_limit, producer_limit, source, plan_code)."""
    sub = get_subscription(session, organization_id)
    if sub is None:
        return None, None, "pending", None
    plan_code = sub.plan_code
    if (sub.seats_limits_source or "").lower() == "en1":
        # Persisted from entitlement.limits — None means unlimited for that bucket
        return sub.internal_seats_limit, sub.producer_seats_limit, "en1", plan_code
    cat_i, cat_p = _plan_catalog_limits(plan_code)
    if sub.billing_provider == "en1":
        return cat_i, cat_p, "en1_plan_mirror", plan_code
    return cat_i, cat_p, "plan_catalog", plan_code


def seat_snapshot(session: Session, organization_id: str) -> SeatSnapshot:
    internal_lim, producer_lim, source, plan_code = resolve_seat_limits(
        session, organization_id
    )
    return SeatSnapshot(
        organization_id=organization_id,
        plan_code=plan_code,
        source=source,
        internal=SeatBucket(
            limit=internal_lim,
            used=count_internal_seats_used(session, organization_id),
        ),
        producer=SeatBucket(
            limit=producer_lim,
            used=count_producer_seats_used(session, organization_id),
        ),
    )


def _role_bucket(role_code: str) -> str:
    role = (role_code or BROKER).upper()
    if role == PRODUCER:
        return "producer"
    if role == PLATFORM:
        return "platform"
    return "internal"


def assert_can_activate_role(
    session: Session,
    *,
    organization_id: str,
    role_code: str,
    existing: OrgMembership | None = None,
) -> SeatSnapshot:
    """Fail if activating ``role_code`` would exceed seats.

    Reactivating same role for same membership does not consume an extra seat.
    Switching internal→producer frees internal and consumes producer (checked).
    """
    snap = seat_snapshot(session, organization_id)
    role = (role_code or BROKER).upper()
    bucket = _role_bucket(role)
    if bucket == "platform":
        return snap

    holding = existing is not None and _membership_holds_seat(existing)
    if holding and (existing.role_code or "").upper() == role:
        return snap

    if bucket == "internal":
        used = snap.internal.used
        if holding:
            prev = _role_bucket(existing.role_code or BROKER)
            if prev == "internal":
                return snap  # already counted
        if snap.internal.limit is not None and used >= snap.internal.limit:
            raise SeatLimitError(
                f"internal_seats exhausted ({used}/{snap.internal.limit})"
            )
        return snap

    # producer
    used = snap.producer.used
    if holding:
        prev = _role_bucket(existing.role_code or BROKER)
        if prev == "producer":
            return snap
    if snap.producer.limit is not None and used >= snap.producer.limit:
        raise SeatLimitError(
            f"producer_seats exhausted ({used}/{snap.producer.limit})"
        )
    return snap


def activate_membership(
    session: Session,
    *,
    subject_id: str,
    organization_id: str,
    role_code: str,
    display_name: str | None = None,
    enforce_seats: bool = True,
) -> OrgMembership:
    """Create/update membership with optional seat enforcement (F5/F7)."""
    from corredores.services.org_access_admin import set_membership_status

    role = (role_code or BROKER).upper()
    row = (
        session.query(OrgMembership)
        .filter_by(subject_id=subject_id, organization_id=organization_id)
        .one_or_none()
    )
    if enforce_seats:
        assert_can_activate_role(
            session,
            organization_id=organization_id,
            role_code=role,
            existing=row,
        )
    if row is None:
        row = OrgMembership(
            subject_id=subject_id,
            organization_id=organization_id,
            display_name=display_name,
            role_code=role,
        )
        set_membership_status(row, MEMBERSHIP_STATUS_ACTIVE)
        session.add(row)
    else:
        row.role_code = role
        if display_name:
            row.display_name = display_name
        set_membership_status(row, MEMBERSHIP_STATUS_ACTIVE)
    session.flush()
    return row


def grant_producer_system_access(
    session: Session,
    *,
    organization_id: str,
    producer_profile_id: str,
    subject_id: str,
    display_name: str | None = None,
) -> OrgMembership:
    """Link system access (PRODUCER membership) to a ProducerProfile — consumes producer_seat."""
    profile = session.get(ProducerProfile, producer_profile_id)
    if profile is None or profile.organization_id != organization_id:
        raise SeatLimitError("producer profile not found")
    if (profile.status or "").upper() != PRODUCER_STATUS_ACTIVE:
        raise SeatLimitError("producer profile is not ACTIVE")
    return activate_membership(
        session,
        subject_id=subject_id,
        organization_id=organization_id,
        role_code=PRODUCER,
        display_name=display_name or profile.display_name,
        enforce_seats=True,
    )
