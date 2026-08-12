"""Request helpers — control-plane + tenant context (ADR-006 / ADR-007)."""

from __future__ import annotations

from contextvars import ContextVar, Token

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from corredores.config import settings
from corredores.control_plane import Actor, AllowAllEntitlements, OrganizationContext
from corredores.db import SessionLocal
from corredores.domain.models import Organization
from corredores.services.tenant import (
    assert_membership,
    get_organization,
    list_memberships,
)
from corredores.web.auth_session import read_session

_request_var: ContextVar[Request | None] = ContextVar("esb_request", default=None)


def bind_request(request: Request) -> Token:
    return _request_var.set(request)


def reset_request(token: Token) -> None:
    _request_var.reset(token)


def current_request() -> Request | None:
    return _request_var.get()


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


def current_actor(request: Request | None = None) -> Actor:
    req = request or current_request()
    if req is not None:
        principal = read_session(req)
        if principal is not None:
            display = settings.auth_display_name or principal.username
            return Actor(actor_id=principal.actor_id, display_name=display)
    if not settings.auth_enabled:
        return Actor(actor_id="piloto-ui", display_name="Broker ESecureBroker")
    return Actor(
        actor_id="piloto-ui",
        display_name=settings.auth_display_name or "Broker ESecureBroker",
    )


def resolve_org(session: Session, request: Request | None = None) -> Organization:
    """Active tenant from signed session membership — never trust client-only org id.

    Auth off (tests): first available organization (legacy single-tenant).
    """
    req = request if request is not None else current_request()
    if req is not None and settings.auth_enabled:
        principal = read_session(req)
        if principal is None:
            raise HTTPException(401, "sesión requerida")
        org_id = principal.organization_id
        if not org_id:
            raise HTTPException(403, "organización activa no definida")
        assert_membership(
            session, principal.actor_id, org_id, username=principal.username
        )
        org = get_organization(session, org_id)
        if org is None or not org.active:
            raise HTTPException(403, "organización no disponible")
        return org

    org = session.query(Organization).filter_by(name="ESecureBroker").one_or_none()
    if org is None:
        org = session.query(Organization).filter_by(name="Piloto Corredores").one_or_none()
    if org is None:
        org = session.query(Organization).order_by(Organization.created_at).first()
    if org is None:
        raise RuntimeError("No organization — run cli seed / run-e2e first")
    return org


def current_org_ctx(org: Organization) -> OrganizationContext:
    return OrganizationContext(
        organization_id=org.id,
        name=org.name,
        external_en1_org_id=org.external_en1_org_id,
    )


def entitlements() -> AllowAllEntitlements:
    return AllowAllEntitlements()


def subject_memberships(session: Session, request: Request | None = None) -> list:
    req = request or current_request()
    if req is None:
        return []
    principal = read_session(req)
    if principal is None:
        return []
    return list_memberships(session, principal.actor_id)
