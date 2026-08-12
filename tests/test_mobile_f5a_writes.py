"""ESB GO F5A — activities + document upload Mobile API."""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import corredores.db as db
from corredores.config import settings
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.enums import PartyType
from corredores.domain.membership_roles import OWNER, PRODUCER
from corredores.domain.models import BrokerAccount, OrgSubscription, Party
from corredores.services.producer_portfolio import assign_policy_primary, create_producer_profile
from corredores.services.saas_signup import hash_password
from corredores.services.seats import activate_membership
from corredores.services.seed_tenants import seed_multitenant_demo
from corredores.services.tenant import ensure_membership
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
    owner_email = "owner.f5a@example.invalid"
    owner_subj = actor_id_for_username(owner_email)
    session.add(
        BrokerAccount(
            email=owner_email,
            password_hash=hash_password("secreto123"),
            display_name="Owner F5A",
            subject_id=owner_subj,
            active=True,
        )
    )
    ensure_membership(
        session, subject_id=owner_subj, organization_id=org, role_code=OWNER, display_name="Owner"
    )

    prod_email = "prod.f5a@example.invalid"
    prod_subj = actor_id_for_username(prod_email)
    person = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Prod",
        last_name="F5A",
        email=prod_email,
    )
    session.add(person)
    session.flush()
    session.add(
        BrokerAccount(
            email=prod_email,
            password_hash=hash_password("secreto123"),
            display_name="Prod F5A",
            subject_id=prod_subj,
            active=True,
        )
    )
    profile = create_producer_profile(
        session, organization_id=org, party_id=person.id, code="PF5A"
    )
    activate_membership(
        session,
        subject_id=prod_subj,
        organization_id=org,
        role_code=PRODUCER,
        display_name="Prod",
        enforce_seats=True,
    )
    assign_policy_primary(
        session,
        organization_id=org,
        producer_profile_id=profile.id,
        policy_id=info["alfa"]["policy_id"],
        reason="f5a",
        assigned_by_subject_id=owner_subj,
    )
    session.commit()
    info["owner_email"] = owner_email
    info["prod_email"] = prod_email
    return info


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_secret", "test-f5a-secret")
    return TestClient(create_app())


def _token(client: TestClient, email: str) -> str:
    r = client.post(
        "/api/mobile/v1/auth/login",
        json={"username": email, "password": "secreto123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_owner_create_activity(world, monkeypatch):
    client = _client(monkeypatch)
    h = {"Authorization": f"Bearer {_token(client, world['owner_email'])}"}
    r = client.post(
        "/api/mobile/v1/activities",
        headers=h,
        json={
            "customer_id": world["alfa"]["party_id"],
            "policy_id": world["alfa"]["policy_id"],
            "activity_type": "VISIT",
            "note": "Visita de cobro",
            "client_activity_id": "act-owner-1",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "SYNCED"
    assert body["idempotency"] == "created"
    assert body["activity_type"] == "VISIT"


def test_producer_activity_in_and_out_of_scope(world, monkeypatch):
    client = _client(monkeypatch)
    h = {"Authorization": f"Bearer {_token(client, world['prod_email'])}"}
    ok = client.post(
        "/api/mobile/v1/activities",
        headers=h,
        json={
            "customer_id": world["alfa"]["party_id"],
            "policy_id": world["alfa"]["policy_id"],
            "activity_type": "NOTE",
            "note": "Nota productor",
            "client_activity_id": "act-prod-1",
        },
    )
    assert ok.status_code == 200, ok.text
    deny = client.post(
        "/api/mobile/v1/activities",
        headers=h,
        json={
            "customer_id": world["beta"]["party_id"],
            "activity_type": "NOTE",
            "note": "cruzado",
            "client_activity_id": "act-prod-x",
        },
    )
    assert deny.status_code == 404


def test_upload_idempotent_and_conflict(world, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_root", str(tmp_path / "docs"))
    client = _client(monkeypatch)
    h = {"Authorization": f"Bearer {_token(client, world['owner_email'])}"}
    # minimal jpeg header
    content = b"\xff\xd8\xff\xd9" + b"hello-photo"
    files = {"file": ("foto.jpg", BytesIO(content), "image/jpeg")}
    data = {
        "customer_id": world["alfa"]["party_id"],
        "policy_id": world["alfa"]["policy_id"],
        "document_type": "CEDULA",
        "client_upload_id": "up-1",
        "title": "Cedula",
    }
    r1 = client.post("/api/mobile/v1/documents/upload", headers=h, data=data, files=files)
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "SYNCED"
    assert r1.json()["idempotency"] == "created"
    doc_id = r1.json()["document_id"]

    files2 = {"file": ("foto.jpg", BytesIO(content), "image/jpeg")}
    r2 = client.post("/api/mobile/v1/documents/upload", headers=h, data=data, files=files2)
    assert r2.status_code == 200, r2.text
    assert r2.json()["idempotency"] == "replayed"
    assert r2.json()["document_id"] == doc_id

    bad = {
        **data,
        "document_type": "LICENCIA",
    }
    files3 = {"file": ("foto.jpg", BytesIO(content), "image/jpeg")}
    r3 = client.post("/api/mobile/v1/documents/upload", headers=h, data=bad, files=files3)
    assert r3.status_code == 409


def test_producer_upload_out_of_scope(world, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_root", str(tmp_path / "docs"))
    client = _client(monkeypatch)
    h = {"Authorization": f"Bearer {_token(client, world['prod_email'])}"}
    content = b"\xff\xd8\xff\xd9xx"
    files = {"file": ("x.jpg", BytesIO(content), "image/jpeg")}
    r = client.post(
        "/api/mobile/v1/documents/upload",
        headers=h,
        data={
            "customer_id": world["beta"]["party_id"],
            "document_type": "OTRO",
            "client_upload_id": "up-oos",
        },
        files=files,
    )
    assert r.status_code == 404


def test_upload_validation_empty(world, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_root", str(tmp_path / "docs"))
    client = _client(monkeypatch)
    h = {"Authorization": f"Bearer {_token(client, world['owner_email'])}"}
    files = {"file": ("empty.jpg", BytesIO(b""), "image/jpeg")}
    r = client.post(
        "/api/mobile/v1/documents/upload",
        headers=h,
        data={
            "customer_id": world["alfa"]["party_id"],
            "document_type": "OTRO",
            "client_upload_id": "up-empty",
        },
        files=files,
    )
    assert r.status_code == 400
