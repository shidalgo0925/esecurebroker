"""Auth dependencies for Mobile API v1."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from corredores.db import SessionLocal
from corredores.domain.models import Organization, OrgMembership
from corredores.services.tenant import assert_membership, is_platform_admin
from corredores.web.mobile.errors import MobileAPIError
from corredores.web.mobile.tokens import AccessPrincipal, parse_access_token


def get_db():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@dataclass
class MobileContext:
    principal: AccessPrincipal
    organization: Organization | None
    membership: OrgMembership | None
    role_code: str
    is_platform: bool


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise MobileAPIError(
            "unauthorized",
            "Missing or invalid Authorization Bearer token.",
            status_code=401,
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise MobileAPIError("unauthorized", "Empty Bearer token.", status_code=401)
    return token


def require_access(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_db),
) -> MobileContext:
    token = _bearer(authorization)
    principal = parse_access_token(token)
    is_plat = is_platform_admin(
        session, principal.subject_id, username=principal.username
    )
    org: Organization | None = None
    membership: OrgMembership | None = None
    role = "BROKER"
    if principal.organization_id:
        org = session.get(Organization, principal.organization_id)
        if org is None or not org.active:
            raise MobileAPIError(
                "organization_unavailable",
                "Organization is not available.",
                status_code=403,
            )
        try:
            membership = assert_membership(
                session,
                principal.subject_id,
                org.id,
                username=principal.username,
            )
            role = membership.role_code if membership else ("PLATFORM" if is_plat else "BROKER")
        except Exception as e:
            # assert_membership raises HTTPException — map to MobileAPIError
            from fastapi import HTTPException

            if isinstance(e, HTTPException):
                raise MobileAPIError(
                    "forbidden",
                    "No membership for this organization.",
                    status_code=403,
                ) from e
            raise
        if membership is None and is_plat:
            role = "PLATFORM"
    return MobileContext(
        principal=principal,
        organization=org,
        membership=membership,
        role_code=role,
        is_platform=is_plat,
    )


def require_org_context(ctx: MobileContext = Depends(require_access)) -> MobileContext:
    if ctx.organization is None:
        raise MobileAPIError(
            "organization_required",
            "Select an organization first (POST /api/mobile/v1/session/organization).",
            status_code=403,
            details={"requires_organization_selection": True},
        )
    return ctx
