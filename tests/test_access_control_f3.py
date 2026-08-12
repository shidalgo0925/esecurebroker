"""ADR-008 F3 — Scope enforcement on Mobile lists + Today."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import corredores.db as db
from corredores.config import settings
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.enums import PartyType
from corredores.domain.membership_roles import PRODUCER
from corredores.domain.models import BrokerAccount, OrgSubscription, Party
from corredores.services.access_control import scope_allowlists, resolve_access_context
from corredores.services.producer_portfolio import assign_policy_primary, create_producer_profile
from corredores.services.saas_signup import hash_password
from corredores.services.seed_tenants import seed_multitenant_demo
from corredores.services.tenant import ensure_membership
from corredores.services.today_home import build_today_home
from corredores.web import create_app
from corredores.web.auth_session import actor_id_for_username


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
    prod_email = "prod.f3@example.invalid"
    prod_subj = actor_id_for_username(prod_email)
    person = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Prod",
        last_name="F3",
        email=prod_email,
    )
    session.add(person)
    session.flush()
    session.add(
        BrokerAccount(
            email=prod_email,
            password_hash=hash_password("secreto123"),
            display_name="Prod F3",
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
        session, organization_id=org, party_id=person.id, code="PF3"
    )
    assign_policy_primary(
        session,
        organization_id=org,
        producer_profile_id=profile.id,
        policy_id=info["alfa"]["policy_id"],
    )
    session.commit()
    info["prod_email"] = prod_email
    info["prod_profile_id"] = profile.id
    return info


def _auth_headers(client: TestClient, email: str) -> dict[str, str]:
    login = client.post(
        "/api/mobile/v1/auth/login",
        json={"username": email, "password": "secreto123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_scope_allowlists_producer(session, world):
    ctx = resolve_access_context(
        session,
        subject_id=actor_id_for_username(world["prod_email"]),
        username=world["prod_email"],
        organization_id=world["alfa"]["organization_id"],
    )
    pids, party_ids = scope_allowlists(session, ctx)
    assert pids == frozenset({world["alfa"]["policy_id"]})
    assert world["alfa"]["party_id"] in (party_ids or frozenset())


def test_today_home_scoped(session, world):
    ctx = resolve_access_context(
        session,
        subject_id=actor_id_for_username(world["prod_email"]),
        username=world["prod_email"],
        organization_id=world["alfa"]["organization_id"],
    )
    pids, party_ids = scope_allowlists(session, ctx)
    home = build_today_home(
        session,
        world["alfa"]["organization_id"],
        today=date(2026, 8, 10),
        policy_ids=pids,
        party_ids=party_ids,
    )
    for card in home.attention:
        if card.policy_id:
            assert card.policy_id in pids


def test_mobile_lists_scoped_to_portfolio(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_secret", "test-f3-secret")
    client = TestClient(create_app())
    headers = _auth_headers(client, world["prod_email"])

    policies = client.get("/api/mobile/v1/policies", headers=headers)
    assert policies.status_code == 200, policies.text
    ids = {p["id"] for p in policies.json()["items"]}
    assert ids == {world["alfa"]["policy_id"]}
    assert world["beta"]["policy_id"] not in ids

    customers = client.get("/api/mobile/v1/customers", headers=headers)
    assert customers.status_code == 200, customers.text
    cids = {c["id"] for c in customers.json()["items"]}
    assert world["alfa"]["party_id"] in cids
    assert world["beta"]["party_id"] not in cids

    today = client.get("/api/mobile/v1/today", headers=headers)
    assert today.status_code == 200, today.text
    body = today.json()
    assert "attention" in body
    assert "money" in body
