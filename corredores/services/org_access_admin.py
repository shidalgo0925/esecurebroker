"""ADR-008 F7 — Collaborators, roles, invitations (domain services)."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from corredores.domain.membership_roles import (
    ADMIN,
    BROKER,
    CANONICAL_ROLE_CODES,
    COLLECTIONS,
    DEFAULT_SCOPE_BY_ROLE,
    MEMBERSHIP_STATUS_ACTIVE,
    MEMBERSHIP_STATUS_INACTIVE,
    MEMBERSHIP_STATUS_INVITED,
    MEMBERSHIP_STATUS_REVOKED,
    MEMBERSHIP_STATUSES_SEAT_HOLD,
    ORG_ASSIGNABLE_ROLES,
    OWNER,
    PLATFORM,
    PRODUCER,
)
from corredores.domain.models import (
    AuditEvent,
    BrokerAccount,
    OrgInvitation,
    OrgMembership,
    OrgRole,
    OrgRolePermission,
    ProducerProfile,
)
from corredores.domain.permissions_catalog import (
    CUSTOM_ROLE_FORBIDDEN,
    PERMISSION_CATALOG,
    SYSTEM_ROLE_LABELS,
    SYSTEM_ROLE_PERMISSIONS,
    is_known_permission,
)
from corredores.services.seats import SeatLimitError, assert_can_activate_role, seat_snapshot
from corredores.services.saas_signup import find_account_by_subject, normalize_email


class AccessAdminError(ValueError):
    pass


INVITE_TTL_DAYS = 7
PENDING_SUBJECT_PREFIX = "pending:"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(
    session: Session,
    *,
    organization_id: str,
    actor_id: str | None,
    entity_type: str,
    entity_id: str,
    action: str,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            detail_json=json.dumps(detail or {}, ensure_ascii=False, default=str),
        )
    )


def set_membership_status(row: OrgMembership, status: str) -> None:
    row.status = status
    row.active = status == MEMBERSHIP_STATUS_ACTIVE


def sync_membership_active(row: OrgMembership) -> None:
    """Keep legacy ``active`` aligned with status."""
    if not getattr(row, "status", None):
        row.status = MEMBERSHIP_STATUS_ACTIVE if row.active else MEMBERSHIP_STATUS_INACTIVE
    row.active = row.status == MEMBERSHIP_STATUS_ACTIVE


def pending_subject_for_email(email: str) -> str:
    return f"{PENDING_SUBJECT_PREFIX}{normalize_email(email)}"


def hash_invite_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_system_roles(session: Session) -> None:
    """Idempotent seed of system OrgRole rows (organization_id NULL)."""
    for code in (OWNER, ADMIN, BROKER, PRODUCER, COLLECTIONS):
        existing = (
            session.query(OrgRole)
            .filter(OrgRole.organization_id.is_(None), OrgRole.code == code)
            .one_or_none()
        )
        if existing:
            continue
        session.add(
            OrgRole(
                organization_id=None,
                code=code,
                name=SYSTEM_ROLE_LABELS.get(code, code),
                description=f"Rol de sistema {code}",
                system_role=True,
                active=True,
                default_scope=DEFAULT_SCOPE_BY_ROLE.get(code, "ORGANIZATION"),
            )
        )
    session.flush()


def list_roles_for_org(session: Session, organization_id: str) -> list[OrgRole]:
    ensure_system_roles(session)
    system = (
        session.query(OrgRole)
        .filter(OrgRole.organization_id.is_(None), OrgRole.system_role.is_(True))
        .order_by(OrgRole.code.asc())
        .all()
    )
    custom = (
        session.query(OrgRole)
        .filter_by(organization_id=organization_id)
        .order_by(OrgRole.name.asc())
        .all()
    )
    return list(system) + list(custom)


def get_role(session: Session, organization_id: str, role_id: str) -> OrgRole | None:
    row = session.get(OrgRole, role_id)
    if row is None:
        return None
    if row.organization_id is None and row.system_role:
        return row
    if row.organization_id == organization_id:
        return row
    return None


def permissions_for_org_role(
    session: Session, *, organization_id: str, role_code: str, is_platform: bool = False
) -> list[str]:
    role = (role_code or BROKER).upper()
    if role in SYSTEM_ROLE_PERMISSIONS:
        base = list(SYSTEM_ROLE_PERMISSIONS[role])
        if is_platform or role == PLATFORM:
            if "platform:admin" not in base:
                base.append("platform:admin")
        return sorted(set(base))
    # Custom tenant role
    org_role = (
        session.query(OrgRole)
        .filter_by(organization_id=organization_id, code=role, active=True)
        .one_or_none()
    )
    if org_role is None:
        return sorted(set(SYSTEM_ROLE_PERMISSIONS[BROKER]))
    codes = [
        p.permission_code
        for p in session.query(OrgRolePermission).filter_by(role_id=org_role.id).all()
    ]
    return sorted({c for c in codes if is_known_permission(c) and c not in CUSTOM_ROLE_FORBIDDEN})


def scope_for_org_role(session: Session, *, organization_id: str, role_code: str) -> str:
    role = (role_code or BROKER).upper()
    if role in DEFAULT_SCOPE_BY_ROLE:
        return DEFAULT_SCOPE_BY_ROLE[role]
    org_role = (
        session.query(OrgRole)
        .filter_by(organization_id=organization_id, code=role, active=True)
        .one_or_none()
    )
    if org_role:
        return org_role.default_scope or "ORGANIZATION"
    return "ORGANIZATION"


def _norm_role_code(raw: str) -> str:
    code = re.sub(r"[^A-Z0-9_]+", "", (raw or "").strip().upper().replace(" ", "_").replace("-", "_"))
    return code[:64]


def create_custom_role(
    session: Session,
    *,
    organization_id: str,
    code: str,
    name: str,
    description: str | None,
    default_scope: str,
    permissions: list[str],
    actor_id: str | None,
) -> OrgRole:
    ensure_system_roles(session)
    code_n = _norm_role_code(code)
    name_n = (name or "").strip()
    if not code_n or not name_n:
        raise AccessAdminError("código y nombre de rol requeridos")
    if code_n in CANONICAL_ROLE_CODES:
        raise AccessAdminError("no puedes reutilizar un código de rol de sistema")
    scope = (default_scope or "ORGANIZATION").upper()
    if scope not in {"ORGANIZATION", "ASSIGNED_PORTFOLIO"}:
        raise AccessAdminError("scope inválido")
    clash = (
        session.query(OrgRole)
        .filter_by(organization_id=organization_id, code=code_n)
        .one_or_none()
    )
    if clash:
        raise AccessAdminError(f"ya existe el rol {code_n}")
    perms = sorted(
        {
            p
            for p in permissions
            if is_known_permission(p) and p not in CUSTOM_ROLE_FORBIDDEN
        }
    )
    row = OrgRole(
        organization_id=organization_id,
        code=code_n,
        name=name_n[:120],
        description=(description or "").strip() or None,
        system_role=False,
        active=True,
        default_scope=scope,
    )
    session.add(row)
    session.flush()
    for p in perms:
        session.add(OrgRolePermission(role_id=row.id, permission_code=p))
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="OrgRole",
        entity_id=row.id,
        action="ROLE_CREATED",
        detail={"code": code_n, "permissions": perms, "scope": scope},
    )
    session.flush()
    return row


def update_custom_role(
    session: Session,
    *,
    organization_id: str,
    role_id: str,
    name: str | None = None,
    description: str | None = None,
    default_scope: str | None = None,
    permissions: list[str] | None = None,
    active: bool | None = None,
    actor_id: str | None = None,
) -> OrgRole:
    row = get_role(session, organization_id, role_id)
    if row is None:
        raise AccessAdminError("rol no encontrado")
    if row.system_role or row.organization_id is None:
        raise AccessAdminError("los roles de sistema no se editan")
    before = {"name": row.name, "active": row.active, "scope": row.default_scope}
    if name is not None:
        row.name = name.strip()[:120] or row.name
    if description is not None:
        row.description = description.strip() or None
    if default_scope is not None:
        scope = default_scope.upper()
        if scope not in {"ORGANIZATION", "ASSIGNED_PORTFOLIO"}:
            raise AccessAdminError("scope inválido")
        row.default_scope = scope
    if active is not None:
        row.active = bool(active)
    if permissions is not None:
        session.query(OrgRolePermission).filter_by(role_id=row.id).delete(synchronize_session=False)
        perms = sorted(
            {
                p
                for p in permissions
                if is_known_permission(p) and p not in CUSTOM_ROLE_FORBIDDEN
            }
        )
        for p in perms:
            session.add(OrgRolePermission(role_id=row.id, permission_code=p))
        _audit(
            session,
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="OrgRole",
            entity_id=row.id,
            action="ROLE_PERMISSIONS_CHANGED",
            detail={"permissions": perms},
        )
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="OrgRole",
        entity_id=row.id,
        action="ROLE_UPDATED",
        detail={"before": before, "after": {"name": row.name, "active": row.active, "scope": row.default_scope}},
    )
    session.flush()
    return row


def role_permission_codes(session: Session, role_id: str) -> list[str]:
    return sorted(
        p.permission_code
        for p in session.query(OrgRolePermission).filter_by(role_id=role_id).all()
    )


def list_collaborators(session: Session, organization_id: str) -> list[dict[str, Any]]:
    rows = (
        session.query(OrgMembership)
        .filter_by(organization_id=organization_id)
        .order_by(OrgMembership.created_at.asc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for m in rows:
        email = m.email
        if not email and not m.subject_id.startswith(PENDING_SUBJECT_PREFIX):
            acc = find_account_by_subject(session, m.subject_id)
            email = acc.email if acc else None
        scope = scope_for_org_role(session, organization_id=organization_id, role_code=m.role_code)
        out.append(
            {
                "id": m.id,
                "display_name": m.display_name or email or m.subject_id,
                "email": email,
                "role_code": m.role_code,
                "role_label": SYSTEM_ROLE_LABELS.get(m.role_code, m.role_code),
                "scope": scope,
                "status": m.status or (MEMBERSHIP_STATUS_ACTIVE if m.active else MEMBERSHIP_STATUS_INACTIVE),
                "is_producer": (m.role_code or "").upper() == PRODUCER or bool(m.producer_profile_id),
                "producer_profile_id": m.producer_profile_id,
                "last_access_at": m.last_access_at,
                "created_at": m.created_at,
                "subject_id": m.subject_id,
            }
        )
    return out


def get_membership_in_org(
    session: Session, organization_id: str, membership_id: str
) -> OrgMembership | None:
    row = session.get(OrgMembership, membership_id)
    if row is None or row.organization_id != organization_id:
        return None
    return row


def count_active_owners(session: Session, organization_id: str) -> int:
    return (
        session.query(OrgMembership)
        .filter_by(
            organization_id=organization_id,
            role_code=OWNER,
            status=MEMBERSHIP_STATUS_ACTIVE,
        )
        .count()
    )


def _validate_assignable_role(session: Session, organization_id: str, role_code: str) -> str:
    role = (role_code or "").strip().upper()
    if not role:
        raise AccessAdminError("rol requerido")
    if role == PLATFORM:
        raise AccessAdminError("PLATFORM no se administra desde la correduría")
    if role in ORG_ASSIGNABLE_ROLES:
        return role
    custom = (
        session.query(OrgRole)
        .filter_by(organization_id=organization_id, code=role, active=True)
        .one_or_none()
    )
    if custom is None:
        raise AccessAdminError(f"rol no válido: {role}")
    return role


def invite_collaborator(
    session: Session,
    *,
    organization_id: str,
    email: str,
    display_name: str,
    role_code: str,
    actor_subject_id: str | None,
    link_producer_profile_id: str | None = None,
) -> tuple[OrgMembership, OrgInvitation, str]:
    """Create INVITED membership + invitation. Returns (membership, invitation, raw_token)."""
    email_n = normalize_email(email)
    name = (display_name or "").strip() or email_n
    role = _validate_assignable_role(session, organization_id, role_code)

    pending = pending_subject_for_email(email_n)
    existing = (
        session.query(OrgMembership)
        .filter_by(organization_id=organization_id, subject_id=pending)
        .one_or_none()
    )
    if existing and existing.status in MEMBERSHIP_STATUSES_SEAT_HOLD:
        raise AccessAdminError("ya hay una invitación o acceso para ese correo")

    # Existing active account in this org?
    acc = session.query(BrokerAccount).filter_by(email=email_n, active=True).one_or_none()
    if acc:
        mem = (
            session.query(OrgMembership)
            .filter_by(organization_id=organization_id, subject_id=acc.subject_id)
            .one_or_none()
        )
        if mem and mem.status in MEMBERSHIP_STATUSES_SEAT_HOLD:
            raise AccessAdminError("ese correo ya tiene acceso en esta organización")

    try:
        assert_can_activate_role(
            session,
            organization_id=organization_id,
            role_code=role,
            existing=existing if existing and existing.status in MEMBERSHIP_STATUSES_SEAT_HOLD else None,
        )
    except SeatLimitError as exc:
        raise AccessAdminError(
            "Llegaste al límite de colaboradores de tu plan. Administra el plan para ampliar seats."
        ) from exc

    producer_id = None
    if role == PRODUCER and link_producer_profile_id:
        prof = session.get(ProducerProfile, link_producer_profile_id)
        if prof is None or prof.organization_id != organization_id:
            raise AccessAdminError("productor no encontrado")
        producer_id = prof.id

    now = _now()
    if existing is None:
        membership = OrgMembership(
            organization_id=organization_id,
            subject_id=pending,
            display_name=name,
            email=email_n,
            role_code=role,
            producer_profile_id=producer_id,
            invited_at=now,
            invited_by_subject_id=actor_subject_id,
        )
        set_membership_status(membership, MEMBERSHIP_STATUS_INVITED)
        session.add(membership)
        session.flush()
    else:
        membership = existing
        membership.display_name = name
        membership.email = email_n
        membership.role_code = role
        membership.producer_profile_id = producer_id
        membership.invited_at = now
        membership.invited_by_subject_id = actor_subject_id
        membership.revoked_at = None
        set_membership_status(membership, MEMBERSHIP_STATUS_INVITED)
        session.flush()

    # Revoke prior pending invites for this membership
    for old in (
        session.query(OrgInvitation)
        .filter_by(membership_id=membership.id, status="PENDING")
        .all()
    ):
        old.status = "REVOKED"
        old.revoked_at = now

    raw = secrets.token_urlsafe(32)
    inv = OrgInvitation(
        organization_id=organization_id,
        membership_id=membership.id,
        email=email_n,
        role_code=role,
        token_hash=hash_invite_token(raw),
        status="PENDING",
        expires_at=now + timedelta(days=INVITE_TTL_DAYS),
        created_by_subject_id=actor_subject_id,
    )
    session.add(inv)
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_subject_id,
        entity_type="OrgMembership",
        entity_id=membership.id,
        action="MEMBER_INVITED",
        detail={"email": email_n, "role_code": role, "invitation_id": inv.id},
    )
    session.flush()
    return membership, inv, raw


def resend_invitation(
    session: Session,
    *,
    organization_id: str,
    membership_id: str,
    actor_subject_id: str | None,
) -> tuple[OrgInvitation, str]:
    membership = get_membership_in_org(session, organization_id, membership_id)
    if membership is None:
        raise AccessAdminError("colaborador no encontrado")
    if membership.status != MEMBERSHIP_STATUS_INVITED:
        raise AccessAdminError("solo se reenvía si el estado es INVITED")
    now = _now()
    for old in (
        session.query(OrgInvitation)
        .filter_by(membership_id=membership.id, status="PENDING")
        .all()
    ):
        old.status = "REVOKED"
        old.revoked_at = now
    raw = secrets.token_urlsafe(32)
    inv = OrgInvitation(
        organization_id=organization_id,
        membership_id=membership.id,
        email=membership.email or "",
        role_code=membership.role_code,
        token_hash=hash_invite_token(raw),
        status="PENDING",
        expires_at=now + timedelta(days=INVITE_TTL_DAYS),
        created_by_subject_id=actor_subject_id,
    )
    session.add(inv)
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_subject_id,
        entity_type="OrgMembership",
        entity_id=membership.id,
        action="MEMBER_INVITATION_RESENT",
        detail={"invitation_id": inv.id},
    )
    session.flush()
    return inv, raw


def accept_invitation(
    session: Session,
    *,
    raw_token: str,
    password: str,
    display_name: str | None = None,
) -> OrgMembership:
    """Accept invite: create/link BrokerAccount and activate membership."""
    from corredores.identity_ids import actor_id_for_username
    from corredores.services.saas_signup import hash_password

    th = hash_invite_token(raw_token)
    inv = session.query(OrgInvitation).filter_by(token_hash=th).one_or_none()
    if inv is None or inv.status != "PENDING":
        raise AccessAdminError("invitación inválida o ya usada")
    now = _now()
    exp = inv.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        inv.status = "EXPIRED"
        session.flush()
        raise AccessAdminError("invitación expirada")

    membership = session.get(OrgMembership, inv.membership_id)
    if membership is None or membership.organization_id != inv.organization_id:
        raise AccessAdminError("membresía no encontrada")

    email = normalize_email(inv.email)
    acc = session.query(BrokerAccount).filter_by(email=email).one_or_none()
    name = (display_name or membership.display_name or email).strip()
    if acc is None:
        if len(password or "") < 8:
            raise AccessAdminError("la contraseña debe tener al menos 8 caracteres")
        subject_id = actor_id_for_username(email)
        acc = BrokerAccount(
            email=email,
            password_hash=hash_password(password),
            display_name=name,
            subject_id=subject_id,
            active=True,
        )
        session.add(acc)
        session.flush()
    else:
        if not acc.active:
            raise AccessAdminError("cuenta desactivada")
        if password and len(password) >= 8:
            acc.password_hash = hash_password(password)
        subject_id = acc.subject_id

    # Move subject from pending → real (unique constraint)
    other = (
        session.query(OrgMembership)
        .filter_by(organization_id=membership.organization_id, subject_id=subject_id)
        .one_or_none()
    )
    if other and other.id != membership.id:
        raise AccessAdminError("ya existe membresía para esta cuenta en la organización")

    try:
        assert_can_activate_role(
            session,
            organization_id=membership.organization_id,
            role_code=membership.role_code,
            existing=membership,
        )
    except SeatLimitError as exc:
        raise AccessAdminError("sin cupo de seats para activar; contacta al administrador") from exc

    membership.subject_id = subject_id
    membership.email = email
    membership.display_name = name
    membership.accepted_at = now
    set_membership_status(membership, MEMBERSHIP_STATUS_ACTIVE)

    if membership.role_code == PRODUCER and not membership.producer_profile_id:
        _link_or_create_producer(session, membership)

    inv.status = "ACCEPTED"
    inv.accepted_at = now
    _audit(
        session,
        organization_id=membership.organization_id,
        actor_id=subject_id,
        entity_type="OrgMembership",
        entity_id=membership.id,
        action="MEMBER_ACTIVATED",
        detail={"via": "invitation", "role_code": membership.role_code},
    )
    session.flush()
    return membership


def change_member_role(
    session: Session,
    *,
    organization_id: str,
    membership_id: str,
    new_role: str,
    actor_subject_id: str | None,
) -> OrgMembership:
    membership = get_membership_in_org(session, organization_id, membership_id)
    if membership is None:
        raise AccessAdminError("colaborador no encontrado")
    role = _validate_assignable_role(session, organization_id, new_role)
    old = membership.role_code
    if old == OWNER and role != OWNER:
        if count_active_owners(session, organization_id) <= 1 and membership.status == MEMBERSHIP_STATUS_ACTIVE:
            raise AccessAdminError("debe quedar al menos un OWNER activo")
    if membership.status in MEMBERSHIP_STATUSES_SEAT_HOLD:
        try:
            assert_can_activate_role(
                session,
                organization_id=organization_id,
                role_code=role,
                existing=membership,
            )
        except SeatLimitError as exc:
            raise AccessAdminError(
                "Llegaste al límite de colaboradores de tu plan."
            ) from exc
    membership.role_code = role
    if role == PRODUCER and not membership.producer_profile_id:
        _link_or_create_producer(session, membership)
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_subject_id,
        entity_type="OrgMembership",
        entity_id=membership.id,
        action="MEMBER_ROLE_CHANGED",
        detail={"before": old, "after": role},
    )
    session.flush()
    return membership


def _link_or_create_producer(session: Session, membership: OrgMembership) -> None:
    from corredores.domain.enums import DataSource
    from corredores.domain.models import Party
    from corredores.services.producer_portfolio import create_producer_profile

    email = membership.email
    party = None
    if email:
        party = (
            session.query(Party)
            .filter(
                Party.organization_id == membership.organization_id,
                Party.party_type == "PERSON",
                Party.email.isnot(None),
            )
            .all()
        )
        party = next((p for p in party if (p.email or "").lower() == email.lower()), None)
    if party is None:
        parts = (membership.display_name or "Productor").strip().split(None, 1)
        party = Party(
            organization_id=membership.organization_id,
            party_type="PERSON",
            first_name=parts[0] if parts else "Productor",
            last_name=parts[1] if len(parts) > 1 else None,
            email=email,
            data_source=DataSource.MANUAL,
        )
        session.add(party)
        session.flush()
    existing = (
        session.query(ProducerProfile)
        .filter_by(organization_id=membership.organization_id, party_id=party.id)
        .one_or_none()
    )
    if existing:
        membership.producer_profile_id = existing.id
    else:
        prof = create_producer_profile(
            session,
            organization_id=membership.organization_id,
            party_id=party.id,
            display_name=membership.display_name or party.first_name or "Productor",
            code=None,
        )
        membership.producer_profile_id = prof.id
    _audit(
        session,
        organization_id=membership.organization_id,
        actor_id=membership.subject_id,
        entity_type="OrgMembership",
        entity_id=membership.id,
        action="PRODUCER_LINKED",
        detail={"producer_profile_id": membership.producer_profile_id},
    )


def deactivate_member(
    session: Session,
    *,
    organization_id: str,
    membership_id: str,
    actor_subject_id: str | None,
) -> OrgMembership:
    membership = get_membership_in_org(session, organization_id, membership_id)
    if membership is None:
        raise AccessAdminError("colaborador no encontrado")
    if membership.status != MEMBERSHIP_STATUS_ACTIVE:
        raise AccessAdminError("solo se desactivan miembros ACTIVE")
    if membership.role_code == OWNER and count_active_owners(session, organization_id) <= 1:
        raise AccessAdminError("no puedes desactivar al último OWNER activo")
    set_membership_status(membership, MEMBERSHIP_STATUS_INACTIVE)
    revoke_subject_refresh_tokens(session, membership.subject_id, organization_id)
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_subject_id,
        entity_type="OrgMembership",
        entity_id=membership.id,
        action="MEMBER_DEACTIVATED",
        detail={},
    )
    session.flush()
    return membership


def activate_member(
    session: Session,
    *,
    organization_id: str,
    membership_id: str,
    actor_subject_id: str | None,
) -> OrgMembership:
    membership = get_membership_in_org(session, organization_id, membership_id)
    if membership is None:
        raise AccessAdminError("colaborador no encontrado")
    if membership.status == MEMBERSHIP_STATUS_REVOKED:
        raise AccessAdminError("un acceso REVOKED no se reactiva así; emite nueva invitación")
    if membership.status == MEMBERSHIP_STATUS_INVITED:
        raise AccessAdminError("la invitación debe aceptarse por el colaborador")
    if membership.subject_id.startswith(PENDING_SUBJECT_PREFIX):
        raise AccessAdminError("sin cuenta vinculada")
    try:
        assert_can_activate_role(
            session,
            organization_id=organization_id,
            role_code=membership.role_code,
            existing=membership,
        )
    except SeatLimitError as exc:
        raise AccessAdminError(
            "Llegaste al límite de colaboradores de tu plan."
        ) from exc
    set_membership_status(membership, MEMBERSHIP_STATUS_ACTIVE)
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_subject_id,
        entity_type="OrgMembership",
        entity_id=membership.id,
        action="MEMBER_ACTIVATED",
        detail={"via": "admin"},
    )
    session.flush()
    return membership


def revoke_member(
    session: Session,
    *,
    organization_id: str,
    membership_id: str,
    actor_subject_id: str | None,
) -> OrgMembership:
    membership = get_membership_in_org(session, organization_id, membership_id)
    if membership is None:
        raise AccessAdminError("colaborador no encontrado")
    if (
        membership.role_code == OWNER
        and membership.status == MEMBERSHIP_STATUS_ACTIVE
        and count_active_owners(session, organization_id) <= 1
    ):
        raise AccessAdminError("no puedes revocar al último OWNER activo")
    now = _now()
    set_membership_status(membership, MEMBERSHIP_STATUS_REVOKED)
    membership.revoked_at = now
    membership.revoked_by_subject_id = actor_subject_id
    for inv in (
        session.query(OrgInvitation)
        .filter_by(membership_id=membership.id, status="PENDING")
        .all()
    ):
        inv.status = "REVOKED"
        inv.revoked_at = now
    revoke_subject_refresh_tokens(session, membership.subject_id, organization_id)
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_subject_id,
        entity_type="OrgMembership",
        entity_id=membership.id,
        action="MEMBER_REVOKED",
        detail={},
    )
    session.flush()
    return membership


def revoke_subject_refresh_tokens(
    session: Session, subject_id: str, organization_id: str | None = None
) -> int:
    from corredores.domain.models import MobileRefreshToken

    q = session.query(MobileRefreshToken).filter_by(subject_id=subject_id)
    if organization_id:
        q = q.filter(
            (MobileRefreshToken.organization_id == organization_id)
            | (MobileRefreshToken.organization_id.is_(None))
        )
    n = 0
    now = _now()
    for row in q.filter(MobileRefreshToken.revoked_at.is_(None)).all():
        row.revoked_at = now
        n += 1
    if n:
        session.flush()
    return n


def seats_banner(session: Session, organization_id: str) -> dict[str, Any]:
    snap = seat_snapshot(session, organization_id)
    return snap.public_dict()
