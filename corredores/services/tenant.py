"""ADR-007 — tenant membership and org-scoped access helpers.

Piloto memberships bind auth subject_id → Organization.
EN1 will replace subject resolution (ADR-006); do not grow into a user registry.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from corredores.domain.models import OrgMembership, Organization


def list_memberships(session: Session, subject_id: str) -> list[OrgMembership]:
    return (
        session.query(OrgMembership)
        .filter_by(subject_id=subject_id, active=True)
        .order_by(OrgMembership.created_at.asc())
        .all()
    )


def ensure_membership(
    session: Session,
    *,
    subject_id: str,
    organization_id: str,
    display_name: str | None = None,
    role_code: str = "BROKER",
) -> OrgMembership:
    row = (
        session.query(OrgMembership)
        .filter_by(subject_id=subject_id, organization_id=organization_id)
        .one_or_none()
    )
    if row is None:
        row = OrgMembership(
            subject_id=subject_id,
            organization_id=organization_id,
            display_name=display_name,
            role_code=role_code,
            active=True,
        )
        session.add(row)
        session.flush()
        return row
    row.active = True
    if display_name:
        row.display_name = display_name
    session.flush()
    return row


def membership_for_org(
    session: Session, subject_id: str, organization_id: str
) -> OrgMembership | None:
    return (
        session.query(OrgMembership)
        .filter_by(subject_id=subject_id, organization_id=organization_id, active=True)
        .one_or_none()
    )


def assert_membership(session: Session, subject_id: str, organization_id: str) -> OrgMembership:
    row = membership_for_org(session, subject_id, organization_id)
    if row is None:
        raise HTTPException(403, "sin membresía en esta organización")
    return row


def get_organization(session: Session, organization_id: str) -> Organization | None:
    return session.get(Organization, organization_id)


def require_org_owned(
    session: Session,
    model: type,
    entity_id: str,
    organization_id: str,
    *,
    not_found: str = "no encontrado",
):
    """Load entity by PK and verify organization_id. 404 on missing or wrong tenant."""
    entity = session.get(model, entity_id)
    if entity is None:
        raise HTTPException(404, not_found)
    own_org = getattr(entity, "organization_id", None)
    if own_org is None or own_org != organization_id:
        # Same status as missing — do not leak cross-tenant existence
        raise HTTPException(404, not_found)
    return entity


def pick_active_organization_id(
    session: Session,
    subject_id: str,
    preferred_org_id: str | None = None,
) -> str | None:
    memberships = list_memberships(session, subject_id)
    if not memberships:
        return None
    if preferred_org_id:
        for m in memberships:
            if m.organization_id == preferred_org_id:
                return preferred_org_id
    return memberships[0].organization_id
