"""ADR-007 — tenant membership and org-scoped access helpers.

Piloto memberships bind auth subject_id → Organization.
EN1 will replace subject resolution (ADR-006); do not grow into a user registry.

Platform admin (dueño SaaS) may enter any org — see is_platform_admin.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from corredores.domain.models import Carrier, OrgMembership, Organization, Party, Policy


def _csv_lower(raw: str) -> set[str]:
    return {p.strip().lower() for p in (raw or "").split(",") if p.strip()}


def is_platform_admin(session: Session, subject_id: str, *, username: str | None = None) -> bool:
    """Dueño de plataforma ESecureBroker — acceso cross-org controlado (DB mantenimiento)."""
    from corredores.services.runtime_settings import runtime

    cfg = runtime(session)
    emails = _csv_lower(cfg.get("platform.admin_emails"))
    users = _csv_lower(cfg.get("platform.admin_usernames"))
    # Bootstrap legacy: si DB vacío, permite env una sola vez vía import — no leemos env aquí.
    if username and username.strip().lower() in users:
        return True
    if subject_id:
        tail = subject_id.split(":", 1)[-1].strip().lower()
        if tail in emails or tail in users:
            return True
    if emails:
        from corredores.services.saas_signup import find_account_by_subject

        acc = find_account_by_subject(session, subject_id)
        if acc and (acc.email or "").strip().lower() in emails:
            return True
    return False


def list_memberships(session: Session, subject_id: str) -> list[OrgMembership]:
    return (
        session.query(OrgMembership)
        .filter_by(subject_id=subject_id, active=True)
        .order_by(OrgMembership.created_at.asc())
        .all()
    )


def list_accessible_organizations(
    session: Session,
    subject_id: str,
    *,
    username: str | None = None,
) -> list[dict]:
    """Orgs the subject can open. Platform admin → all active orgs with portfolio stats."""
    admin = is_platform_admin(session, subject_id, username=username)
    memberships = {m.organization_id: m for m in list_memberships(session, subject_id)}
    if admin:
        orgs = (
            session.query(Organization)
            .filter_by(active=True)
            .order_by(Organization.name.asc())
            .all()
        )
    else:
        orgs = []
        for oid in memberships:
            org = session.get(Organization, oid)
            if org and org.active:
                orgs.append(org)
        orgs.sort(key=lambda o: o.name.lower())

    rows: list[dict] = []
    for org in orgs:
        m = memberships.get(org.id)
        role = m.role_code if m else ("PLATFORM" if admin else "—")
        n_pol = session.query(Policy).filter_by(organization_id=org.id).count()
        n_cli = session.query(Party).filter_by(organization_id=org.id).count()
        n_cia = session.query(Carrier).filter_by(organization_id=org.id).count()
        rows.append(
            {
                "organization_id": org.id,
                "name": org.name,
                "role": role,
                "policies": n_pol,
                "clients": n_cli,
                "carriers": n_cia,
                "is_platform_access": admin and m is None,
            }
        )
    # Dueño: orgs con cartera primero
    rows.sort(key=lambda r: (-r["policies"], -r["clients"], r["name"].lower()))
    return rows


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


def assert_membership(
    session: Session,
    subject_id: str,
    organization_id: str,
    *,
    username: str | None = None,
) -> OrgMembership | None:
    row = membership_for_org(session, subject_id, organization_id)
    if row is not None:
        return row
    if is_platform_admin(session, subject_id, username=username):
        org = get_organization(session, organization_id)
        if org is None or not org.active:
            raise HTTPException(403, "organización no disponible")
        # Acceso dueño: membership virtual (no se materializa salvo que elija entrar)
        return None
    raise HTTPException(403, "sin membresía en esta organización")


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
