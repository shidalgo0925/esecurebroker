"""Request helpers — control-plane stubs only (ADR-006 deferred)."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from corredores.control_plane import Actor, AllowAllEntitlements, OrganizationContext
from corredores.db import SessionLocal
from corredores.domain.models import Organization


def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def resolve_org(session: Session, name: str = "ESecureBroker") -> Organization:
    org = session.query(Organization).filter_by(name=name).one_or_none()
    if org is None:
        # legacy seed name from early P0
        org = session.query(Organization).filter_by(name="Piloto Corredores").one_or_none()
    if org is None:
        org = session.query(Organization).order_by(Organization.created_at).first()
    if org is None:
        raise RuntimeError("No organization — run cli seed / run-e2e first")
    # Prefer commercial product name going forward
    if org.name != "ESecureBroker":
        org.name = "ESecureBroker"
    return org


def current_actor(_request: Request | None = None) -> Actor:
    return Actor(actor_id="piloto-ui", display_name="Broker ESecureBroker")


def current_org_ctx(org: Organization) -> OrganizationContext:
    return OrganizationContext(
        organization_id=org.id,
        name=org.name,
        external_en1_org_id=org.external_en1_org_id,
    )


def entitlements() -> AllowAllEntitlements:
    return AllowAllEntitlements()
