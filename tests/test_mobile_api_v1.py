"""Gate B — ESB GO Mobile API v1 (DEV)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import corredores.db as db
from corredores.config import settings
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.models import OrgSubscription
from corredores.services.seed_tenants import seed_multitenant_demo
from corredores.web import create_app
from corredores.web.auth_session import actor_id_for_username
from corredores.services.tenant import ensure_membership
from corredores.services.saas_signup import hash_password
from corredores.domain.models import BrokerAccount


@pytest.fixture(scope="module")
def seeded():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as session:
        info = seed_multitenant_demo(session, today=date(2026, 8, 10))
        for org_id in {info["alfa"]["organization_id"], info["beta"]["organization_id"]}:
            if session.query(OrgSubscription).filter_by(organization_id=org_id).one_or_none() is None:
                session.add(
                    OrgSubscription(
                        organization_id=org_id,
                        plan_code="oficina",
                        status="active",
                        billing_provider="piloto",
                    )
                )
        for email, org_id, role in [
            ("owner.alfa@example.invalid", info["alfa"]["organization_id"], "OWNER"),
            ("broker.alfa2@example.invalid", info["alfa"]["organization_id"], "BROKER"),
            ("broker.beta@example.invalid", info["beta"]["organization_id"], "BROKER"),
        ]:
            subj = actor_id_for_username(email)
            session.add(
                BrokerAccount(
                    email=email,
                    password_hash=hash_password("secreto123"),
                    display_name=email.split("@")[0],
                    subject_id=subj,
                    active=True,
                )
            )
            ensure_membership(
                session,
                subject_id=subj,
                organization_id=org_id,
                display_name=email,
                role_code=role,
            )
        session.commit()
        return info


@pytest.fixture
def client(seeded, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_secret", "test-mobile-secret-gate-b")
    monkeypatch.setattr(settings, "auth_password", None)
    monkeypatch.setattr(settings, "auth_users", None)
    return TestClient(create_app())


def _login(client: TestClient, email: str) -> dict:
    r = client.post(
        "/api/mobile/v1/auth/login",
        json={"username": email, "password": "secreto123"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    r = client.get("/api/mobile/v1/health")
    assert r.status_code == 200
    assert r.json()["version"] == "v1"


def test_login_me_today_customer_policy_flow(client, seeded):
    tok = _login(client, "owner.alfa@example.invalid")
    assert tok["token_type"] == "Bearer"
    assert tok["organization_id"] == seeded["alfa"]["organization_id"]
    assert tok["requires_organization_selection"] is False
    headers = {"Authorization": f"Bearer {tok['access_token']}"}

    me = client.get("/api/mobile/v1/me", headers=headers)
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["scope"] == "ORGANIZATION"
    assert body["role"] == "OWNER"
    assert body["organization"]["id"] == seeded["alfa"]["organization_id"]
    assert "today:read" in body["permissions"]
    assert body["entitlements"]["source"] in {"piloto_mirror", "pending", "en1"}
    assert "ASSIGNED_PORTFOLIO" not in str(body)

    today = client.get("/api/mobile/v1/today", headers=headers)
    assert today.status_code == 200, today.text
    th = today.json()
    assert "money" in th and "attention" in th
    assert "system_work" in th and "opportunities" in th

    cust = client.get("/api/mobile/v1/customers", headers=headers)
    assert cust.status_code == 200
    assert cust.json()["count"] >= 1
    assert "national_id" in cust.json()["search_fields"]
    assert "plate" not in cust.json()["search_fields"]

    cid = seeded["alfa"]["party_id"]
    c360 = client.get(f"/api/mobile/v1/customers/{cid}/360", headers=headers)
    assert c360.status_code == 200, c360.text
    assert c360.json()["customer"]["id"] == cid
    assert "policies" in c360.json()

    pid = seeded["alfa"]["policy_id"]
    pol = client.get(f"/api/mobile/v1/policies/{pid}", headers=headers)
    assert pol.status_code == 200, pol.text
    assert pol.json()["id"] == pid
    assert pol.json()["client_party_id"] == cid


def test_refresh_and_logout(client):
    tok = _login(client, "broker.alfa2@example.invalid")
    ref = client.post(
        "/api/mobile/v1/auth/refresh",
        json={"refresh_token": tok["refresh_token"]},
    )
    assert ref.status_code == 200
    new = ref.json()
    assert new["access_token"] != tok["access_token"]
    # old refresh revoked
    again = client.post(
        "/api/mobile/v1/auth/refresh",
        json={"refresh_token": tok["refresh_token"]},
    )
    assert again.status_code == 401
    out = client.post(
        "/api/mobile/v1/auth/logout",
        json={"refresh_token": new["refresh_token"]},
    )
    assert out.status_code == 200


def test_cross_org_deny(client, seeded):
    """Org A token cannot read Org B customer/policy by ID."""
    tok = _login(client, "owner.alfa@example.invalid")
    headers = {"Authorization": f"Bearer {tok['access_token']}"}
    foreign_party = seeded["beta"]["party_id"]
    foreign_policy = seeded["beta"]["policy_id"]
    r1 = client.get(f"/api/mobile/v1/customers/{foreign_party}", headers=headers)
    assert r1.status_code == 404
    assert r1.json()["error"]["code"] == "not_found"
    r2 = client.get(f"/api/mobile/v1/policies/{foreign_policy}", headers=headers)
    assert r2.status_code == 404
    r3 = client.get(f"/api/mobile/v1/customers/{foreign_party}/360", headers=headers)
    assert r3.status_code == 404


def test_cannot_spoof_org_via_select(client, seeded):
    tok = _login(client, "broker.beta@example.invalid")
    headers = {"Authorization": f"Bearer {tok['access_token']}"}
    # Beta user tries to select Alfa org without membership
    r = client.post(
        "/api/mobile/v1/session/organization",
        headers=headers,
        json={"organization_id": seeded["alfa"]["organization_id"]},
    )
    assert r.status_code == 403


def test_openapi_includes_mobile_paths(client):
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json().get("paths", {})
    assert "/api/mobile/v1/auth/login" in paths
    assert "/api/mobile/v1/me" in paths
    assert "/api/mobile/v1/today" in paths
    assert "/api/mobile/v1/customers" in paths
    assert "/api/mobile/v1/policies/{policy_id}" in paths
