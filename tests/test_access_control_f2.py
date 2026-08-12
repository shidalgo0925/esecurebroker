"""ADR-008 F2 — AccessContext / RBAC resolve + scope helpers."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import corredores.db as db
from corredores.config import settings
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.enums import PartyType
from corredores.domain.membership_roles import OWNER, PRODUCER
from corredores.domain.models import BrokerAccount, OrgMembership, OrgSubscription, Party
from corredores.services.access_control import (
    SCOPE_ASSIGNED_PORTFOLIO,
    SCOPE_ORGANIZATION,
    AccessDenied,
    apply_scope_to_policy_query,
    require_party_in_scope,
    require_permission,
    require_policy_in_scope,
    resolve_access_context,
)
from corredores.services.producer_portfolio import assign_policy_primary, create_producer_profile
from corredores.services.saas_signup import hash_password
from corredores.services.seed_tenants import seed_multitenant_demo
from corredores.services.tenant import ensure_membership
from corredores.web import create_app
from corredores.web.auth_session import actor_id_for_username
from corredores.domain.models import Policy


@pytest.fixture()
def session():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as s:
        yield s
        s.rollback()


@pytest.fixture()
def world(session):
    info = seed_multitenant_demo(session, today=date(2026, 8, 10))
    org = info["alfa"]["organization_id"]
    for oid in (info["alfa"]["organization_id"], info["beta"]["organization_id"]):
        if session.query(OrgSubscription).filter_by(organization_id=oid).one_or_none() is None:
            session.add(
                OrgSubscription(
                    organization_id=oid,
                    plan_code="oficina",
                    status="active",
                    billing_provider="piloto",
                )
            )
    # OWNER
    owner_email = "owner.f2@example.invalid"
    owner_subj = actor_id_for_username(owner_email)
    session.add(
        BrokerAccount(
            email=owner_email,
            password_hash=hash_password("secreto123"),
            display_name="Owner F2",
            subject_id=owner_subj,
            active=True,
        )
    )
    ensure_membership(
        session, subject_id=owner_subj, organization_id=org, role_code=OWNER, display_name="Owner"
    )
    # PRODUCER with profile + assignment on alfa policy
    prod_email = "prod.f2@example.invalid"
    prod_subj = actor_id_for_username(prod_email)
    person = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Prod",
        last_name="F2",
        email=prod_email,
    )
    session.add(person)
    session.flush()
    session.add(
        BrokerAccount(
            email=prod_email,
            password_hash=hash_password("secreto123"),
            display_name="Prod F2",
            subject_id=prod_subj,
            active=True,
        )
    )
    ensure_membership(
        session,
        subject_id=prod_subj,
        organization_id=org,
        role_code=PRODUCER,
        display_name="Prod",
    )
    profile = create_producer_profile(
        session, organization_id=org, party_id=person.id, code="PF2"
    )
    assign_policy_primary(
        session,
        organization_id=org,
        producer_profile_id=profile.id,
        policy_id=info["alfa"]["policy_id"],
    )
    session.commit()
    info["owner_email"] = owner_email
    info["prod_email"] = prod_email
    info["prod_profile_id"] = profile.id
    return info


def test_owner_scope_organization(session, world):
    ctx = resolve_access_context(
        session,
        subject_id=actor_id_for_username(world["owner_email"]),
        username=world["owner_email"],
        organization_id=world["alfa"]["organization_id"],
    )
    assert ctx.role == OWNER
    assert ctx.scope == SCOPE_ORGANIZATION
    assert "settings:manage" in ctx.permissions
    require_permission(ctx, "today:read")
    pol = require_policy_in_scope(session, ctx, world["alfa"]["policy_id"])
    assert pol.id == world["alfa"]["policy_id"]


def test_producer_scope_assigned_portfolio(session, world):
    ctx = resolve_access_context(
        session,
        subject_id=actor_id_for_username(world["prod_email"]),
        username=world["prod_email"],
        organization_id=world["alfa"]["organization_id"],
    )
    assert ctx.role == PRODUCER
    assert ctx.scope == SCOPE_ASSIGNED_PORTFOLIO
    assert ctx.producer_profile_id == world["prod_profile_id"]
    # Own policy OK
    require_policy_in_scope(session, ctx, world["alfa"]["policy_id"])
    # Client of assigned policy OK
    require_party_in_scope(session, ctx, world["alfa"]["party_id"])


def test_producer_denied_other_org_policy(session, world):
    ctx = resolve_access_context(
        session,
        subject_id=actor_id_for_username(world["prod_email"]),
        username=world["prod_email"],
        organization_id=world["alfa"]["organization_id"],
    )
    with pytest.raises(AccessDenied) as ei:
        require_policy_in_scope(session, ctx, world["beta"]["policy_id"])
    assert ei.value.not_found is True


def test_apply_scope_filters_policies(session, world):
    ctx = resolve_access_context(
        session,
        subject_id=actor_id_for_username(world["prod_email"]),
        username=world["prod_email"],
        organization_id=world["alfa"]["organization_id"],
    )
    q = session.query(Policy)
    scoped = apply_scope_to_policy_query(q, session, ctx).all()
    assert {p.id for p in scoped} == {world["alfa"]["policy_id"]}


def test_mobile_me_reports_producer_scope(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_secret", "test-f2-secret")
    client = TestClient(create_app())
    login = client.post(
        "/api/mobile/v1/auth/login",
        json={"username": world["prod_email"], "password": "secreto123"},
    )
    assert login.status_code == 200, login.text
    me = client.get(
        "/api/mobile/v1/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["role"] == PRODUCER
    assert body["scope"] == SCOPE_ASSIGNED_PORTFOLIO
    assert body["producer_profile_id"] == world["prod_profile_id"]
    # Detail of assigned policy OK
    r = client.get(
        f"/api/mobile/v1/policies/{world['alfa']['policy_id']}",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert r.status_code == 200
    # Cross-org still 404
    r2 = client.get(
        f"/api/mobile/v1/policies/{world['beta']['policy_id']}",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert r2.status_code == 404
