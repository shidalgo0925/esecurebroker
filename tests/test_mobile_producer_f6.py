"""ADR-008 F6 — ESB GO Producer Mobile API (ASSIGNED_PORTFOLIO end-to-end)."""

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
from corredores.services.access_control import SCOPE_ASSIGNED_PORTFOLIO
from corredores.services.producer_portfolio import assign_policy_primary, create_producer_profile
from corredores.services.saas_signup import hash_password
from corredores.services.seats import activate_membership
from corredores.services.seed_tenants import seed_multitenant_demo
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
def producer_world(session):
    info = seed_multitenant_demo(session, today=date(2026, 8, 10))
    org = info["alfa"]["organization_id"]
    session.query(OrgSubscription).filter_by(organization_id=org).delete()
    session.add(
        OrgSubscription(
            organization_id=org,
            plan_code="broker_red",
            status="active",
            billing_provider="piloto",
        )
    )
    email = "producer.alfa@example.invalid"
    subj = actor_id_for_username(email)
    person = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Prod",
        last_name="Alfa",
        email=email,
    )
    session.add(person)
    session.flush()
    session.add(
        BrokerAccount(
            email=email,
            password_hash=hash_password("secreto123"),
            display_name="Producer Alfa",
            subject_id=subj,
            active=True,
        )
    )
    profile = create_producer_profile(
        session, organization_id=org, party_id=person.id, code="PRODALFA"
    )
    activate_membership(
        session,
        subject_id=subj,
        organization_id=org,
        role_code=PRODUCER,
        display_name="Producer Alfa",
        enforce_seats=True,
    )
    assign_policy_primary(
        session,
        organization_id=org,
        producer_profile_id=profile.id,
        policy_id=info["alfa"]["policy_id"],
        reason="F6 seed",
        assigned_by_subject_id="seed-f6",
    )
    session.commit()
    info["prod_email"] = email
    info["prod_profile_id"] = profile.id
    return info


def _headers(client: TestClient, email: str) -> dict[str, str]:
    login = client.post(
        "/api/mobile/v1/auth/login",
        json={"username": email, "password": "secreto123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_f6_producer_vertical_slice(producer_world, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_secret", "test-f6-secret")
    client = TestClient(create_app())
    headers = _headers(client, producer_world["prod_email"])
    alfa_party = producer_world["alfa"]["party_id"]
    alfa_pol = producer_world["alfa"]["policy_id"]
    beta_party = producer_world["beta"]["party_id"]
    beta_pol = producer_world["beta"]["policy_id"]

    me = client.get("/api/mobile/v1/me", headers=headers)
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["role"] == PRODUCER
    assert body["scope"] == SCOPE_ASSIGNED_PORTFOLIO
    assert body["session"]["scope"] == SCOPE_ASSIGNED_PORTFOLIO
    assert body["producer_profile_id"] == producer_world["prod_profile_id"]
    assert body["session"]["producer_profile_id"] == producer_world["prod_profile_id"]
    assert "customers:list" in body["permissions"]
    seats = body["entitlements"]["seats"]
    assert isinstance(seats, dict)
    assert "producer_seats" in seats
    assert "internal_seats" in seats

    today = client.get("/api/mobile/v1/today", headers=headers)
    assert today.status_code == 200, today.text

    customers = client.get("/api/mobile/v1/customers", headers=headers)
    assert customers.status_code == 200
    cids = {c["id"] for c in customers.json()["items"]}
    assert alfa_party in cids
    assert beta_party not in cids

    c360 = client.get(f"/api/mobile/v1/customers/{alfa_party}/360", headers=headers)
    assert c360.status_code == 200, c360.text
    pol_ids = {p["id"] for p in c360.json()["policies"]}
    assert alfa_pol in pol_ids
    assert beta_pol not in pol_ids

    assert client.get(f"/api/mobile/v1/customers/{beta_party}", headers=headers).status_code == 404
    assert client.get(f"/api/mobile/v1/customers/{beta_party}/360", headers=headers).status_code == 404

    policies = client.get("/api/mobile/v1/policies", headers=headers)
    assert policies.status_code == 200
    pids = {p["id"] for p in policies.json()["items"]}
    assert pids == {alfa_pol}

    assert client.get(f"/api/mobile/v1/policies/{alfa_pol}", headers=headers).status_code == 200
    assert client.get(f"/api/mobile/v1/policies/{beta_pol}", headers=headers).status_code == 404
