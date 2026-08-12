"""ADR-008 — list/detail/360 scope consistency for PRODUCER."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import corredores.db as db
from corredores.config import settings
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.enums import PartyType
from corredores.domain.membership_roles import PRODUCER
from corredores.domain.models import BrokerAccount, OrgSubscription, Party, Policy
from corredores.services.producer_portfolio import (
    assign_policy_primary,
    create_producer_profile,
    set_default_producer,
)
from corredores.services.saas_signup import hash_password
from corredores.services.seats import activate_membership
from corredores.services.seed_tenants import seed_multitenant_demo
from corredores.web import create_app
from corredores.web.auth_session import actor_id_for_username


@pytest.fixture()
def session():
    with db.engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as s:
        yield s
        s.rollback()


@pytest.fixture()
def world(session):
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
    email = "prod.scope@example.invalid"
    subj = actor_id_for_username(email)
    person = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Prod",
        last_name="Scope",
        email=email,
    )
    session.add(person)
    session.flush()
    session.add(
        BrokerAccount(
            email=email,
            password_hash=hash_password("secreto123"),
            display_name="Prod Scope",
            subject_id=subj,
            active=True,
        )
    )
    profile = create_producer_profile(
        session, organization_id=org, party_id=person.id, code="PSCOPE"
    )
    activate_membership(
        session,
        subject_id=subj,
        organization_id=org,
        role_code=PRODUCER,
        display_name="Prod Scope",
        enforce_seats=True,
    )
    assign_policy_primary(
        session,
        organization_id=org,
        producer_profile_id=profile.id,
        policy_id=info["alfa"]["policy_id"],
        reason="scope consistency",
        assigned_by_subject_id=subj,
    )
    # default_producer-only customer (NO portfolio policy) — must NOT be visible
    orphan = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Solo",
        last_name="Default",
    )
    session.add(orphan)
    session.flush()
    set_default_producer(
        session,
        organization_id=org,
        party_id=orphan.id,
        producer_profile_id=profile.id,
    )
    # other client with policy outside portfolio
    other = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Fuera",
        last_name="Cartera",
    )
    session.add(other)
    session.flush()
    base = session.get(Policy, info["alfa"]["policy_id"])
    session.add(
        Policy(
            organization_id=org,
            client_party_id=other.id,
            status="ACTIVE",
            policy_number="OUT-1",
            carrier_id=base.carrier_id,
            insurance_line_id=base.insurance_line_id,
        )
    )
    session.commit()
    info["prod_email"] = email
    info["orphan_party_id"] = orphan.id
    info["other_party_id"] = other.id
    info["prod_profile_id"] = profile.id
    return info


def _headers(client: TestClient, email: str) -> dict[str, str]:
    login = client.post(
        "/api/mobile/v1/auth/login",
        json={"username": email, "password": "secreto123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_listed_customer_has_accessible_360(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_secret", "test-scope-secret")
    client = TestClient(create_app())
    headers = _headers(client, world["prod_email"])

    listed = client.get("/api/mobile/v1/customers", headers=headers)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items, "expected at least the portfolio client"
    ids = {c["id"] for c in items}
    assert world["alfa"]["party_id"] in ids
    assert world["orphan_party_id"] not in ids
    assert world["other_party_id"] not in ids

    for c in items:
        assert c["policies_count"] >= 1
        z = client.get(f"/api/mobile/v1/customers/{c['id']}/360", headers=headers)
        assert z.status_code == 200, f"listed {c['id']} must have 360; got {z.status_code} {z.text}"
        assert len(z.json()["policies"]) >= 1
        # no out-of-portfolio policies
        for pol in z.json()["policies"]:
            assert pol["id"] == world["alfa"]["policy_id"] or pol["id"] in {
                world["alfa"]["policy_id"]
            }


def test_outside_portfolio_list_and_360_404(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_secret", "test-scope-secret")
    client = TestClient(create_app())
    headers = _headers(client, world["prod_email"])

    for cid in (world["orphan_party_id"], world["other_party_id"], world["beta"]["party_id"]):
        assert (
            client.get(f"/api/mobile/v1/customers/{cid}", headers=headers).status_code
            == 404
        )
        assert (
            client.get(f"/api/mobile/v1/customers/{cid}/360", headers=headers).status_code
            == 404
        )
