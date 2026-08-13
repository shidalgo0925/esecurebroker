"""ADR-008 F7 — collaborators / invitations / seats / custom roles."""

from __future__ import annotations

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.membership_roles import (
    ADMIN,
    MEMBERSHIP_STATUS_ACTIVE,
    MEMBERSHIP_STATUS_INVITED,
    OWNER,
    PRODUCER,
)
from corredores.domain.models import Organization
from corredores.services.org_access_admin import (
    AccessAdminError,
    accept_invitation,
    create_custom_role,
    deactivate_member,
    invite_collaborator,
    list_collaborators,
    permissions_for_org_role,
    revoke_member,
)
from corredores.services.seats import count_internal_seats_used, seat_snapshot
from corredores.services.seed_pilot import seed_pilot
from corredores.services.tenant import ensure_membership


def setup_module():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as session:
        seed_pilot(session)
        session.commit()


def _org(session) -> Organization:
    org = session.query(Organization).order_by(Organization.created_at).first()
    assert org is not None
    return org


def test_invite_accept_admin_and_seat_hold():
    with db.SessionLocal() as session:
        org = _org(session)
        ensure_membership(
            session,
            subject_id="piloto:owner@test.local",
            organization_id=org.id,
            display_name="Owner",
            role_code=OWNER,
        )
        session.commit()

    with db.SessionLocal() as session:
        org = _org(session)
        before = count_internal_seats_used(session, org.id)
        _m, _inv, raw = invite_collaborator(
            session,
            organization_id=org.id,
            email="admin.f7@test.local",
            display_name="Admin F7",
            role_code=ADMIN,
            actor_subject_id="piloto:owner@test.local",
        )
        session.commit()
        assert _m.status == MEMBERSHIP_STATUS_INVITED
        assert count_internal_seats_used(session, org.id) == before + 1

    with db.SessionLocal() as session:
        org = _org(session)
        mem = accept_invitation(
            session, raw_token=raw, password="password1", display_name="Admin F7"
        )
        session.commit()
        assert mem.status == MEMBERSHIP_STATUS_ACTIVE
        assert mem.role_code == ADMIN
        rows = list_collaborators(session, org.id)
        assert any(r["email"] == "admin.f7@test.local" and r["status"] == "ACTIVE" for r in rows)


def test_custom_role_permissions():
    with db.SessionLocal() as session:
        org = _org(session)
        role = create_custom_role(
            session,
            organization_id=org.id,
            code="supervisor_reclamos",
            name="Supervisor Reclamos",
            description="solo reclamos",
            default_scope="ORGANIZATION",
            permissions=["claims:read", "claims:manage", "customers:read", "platform:admin"],
            actor_id="t",
        )
        session.commit()
        perms = permissions_for_org_role(session, organization_id=org.id, role_code=role.code)
        assert "claims:manage" in perms
        assert "platform:admin" not in perms


def test_cannot_revoke_last_owner():
    with db.SessionLocal() as session:
        org = _org(session)
        # pick an OWNER membership
        from corredores.domain.models import OrgMembership

        owner = (
            session.query(OrgMembership)
            .filter_by(organization_id=org.id, role_code=OWNER, status=MEMBERSHIP_STATUS_ACTIVE)
            .first()
        )
        if owner is None:
            owner = ensure_membership(
                session,
                subject_id="piloto:solo-owner@test.local",
                organization_id=org.id,
                role_code=OWNER,
                display_name="Solo",
            )
            session.commit()
        try:
            revoke_member(
                session,
                organization_id=org.id,
                membership_id=owner.id,
                actor_subject_id=owner.subject_id,
            )
            assert False, "should block last owner revoke"
        except AccessAdminError:
            pass


def test_deactivate_revokes_not_delete():
    with db.SessionLocal() as session:
        org = _org(session)
        _m, _inv, raw = invite_collaborator(
            session,
            organization_id=org.id,
            email="broker.f7@test.local",
            display_name="Broker F7",
            role_code="BROKER",
            actor_subject_id="piloto:owner@test.local",
        )
        session.commit()
        mem = accept_invitation(session, raw_token=raw, password="password1")
        session.commit()
        mid = mem.id

    with db.SessionLocal() as session:
        org = _org(session)
        deactivate_member(
            session,
            organization_id=org.id,
            membership_id=mid,
            actor_subject_id="piloto:owner@test.local",
        )
        session.commit()
        from corredores.domain.models import OrgMembership

        row = session.get(OrgMembership, mid)
        assert row is not None
        assert row.status == "INACTIVE"
        assert row.active is False


def test_seat_snapshot_still_works():
    with db.SessionLocal() as session:
        org = _org(session)
        snap = seat_snapshot(session, org.id)
        assert snap.internal.used >= 0
        assert "internal_seats" in snap.public_dict()
