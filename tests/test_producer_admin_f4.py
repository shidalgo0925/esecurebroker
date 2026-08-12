"""ADR-008 F4 — Producer Admin (alta / reassign / historial)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import corredores.db as db
from corredores.config import settings
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.membership_roles import OWNER
from corredores.domain.models import BrokerAccount, OrgSubscription, Party
from corredores.domain.enums import PartyType
from corredores.services.producer_portfolio import (
    ProducerPortfolioError,
    active_policy_primary,
    assignment_history_for_policy,
    create_producer_person,
    create_producer_profile,
    reassign_policy_primary,
)
from corredores.services.saas_signup import hash_password
from corredores.services.seed_tenants import seed_multitenant_demo
from corredores.services.tenant import ensure_membership
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
    if session.query(OrgSubscription).filter_by(organization_id=org).one_or_none() is None:
        session.add(
            OrgSubscription(
                organization_id=org,
                plan_code="oficina",
                status="active",
                billing_provider="piloto",
            )
        )
    owner_email = "owner.f4@example.invalid"
    owner_subj = actor_id_for_username(owner_email)
    session.add(
        BrokerAccount(
            email=owner_email,
            password_hash=hash_password("secreto123"),
            display_name="Owner F4",
            subject_id=owner_subj,
            active=True,
        )
    )
    ensure_membership(
        session, subject_id=owner_subj, organization_id=org, role_code=OWNER, display_name="Owner"
    )
    session.commit()
    info["owner_email"] = owner_email
    return info


def test_reassign_requires_reason(session, world):
    org = world["alfa"]["organization_id"]
    person = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Ana",
        last_name="F4",
    )
    session.add(person)
    session.flush()
    p = create_producer_profile(session, organization_id=org, party_id=person.id, code="ANA")
    with pytest.raises(ProducerPortfolioError):
        reassign_policy_primary(
            session,
            organization_id=org,
            producer_profile_id=p.id,
            policy_id=world["alfa"]["policy_id"],
            reason="  ",
            assigned_by_subject_id="actor:1",
        )


def test_reassign_keeps_history(session, world):
    org = world["alfa"]["organization_id"]
    a = create_producer_person(
        session, organization_id=org, first_name="Carlos", last_name="Uno", code="C1"
    )
    b = create_producer_person(
        session, organization_id=org, first_name="Ana", last_name="Dos", code="A2"
    )
    reassign_policy_primary(
        session,
        organization_id=org,
        producer_profile_id=a.id,
        policy_id=world["alfa"]["policy_id"],
        reason="alta inicial",
        assigned_by_subject_id="actor:owner",
    )
    reassign_policy_primary(
        session,
        organization_id=org,
        producer_profile_id=b.id,
        policy_id=world["alfa"]["policy_id"],
        reason="traspaso a Ana",
        assigned_by_subject_id="actor:owner",
    )
    cur = active_policy_primary(
        session, organization_id=org, policy_id=world["alfa"]["policy_id"]
    )
    assert cur is not None
    assert cur.producer_profile_id == b.id
    hist = assignment_history_for_policy(
        session, organization_id=org, policy_id=world["alfa"]["policy_id"]
    )
    assert len(hist) >= 2
    closed = [h for h in hist if h.producer_profile_id == a.id and h.effective_to is not None]
    assert closed


def test_web_productores_list_and_assign(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_secret", "test-f4-secret")
    client = TestClient(create_app())
    login = client.post(
        "/login",
        data={"username": world["owner_email"], "password": "secreto123", "next": "/hoy"},
        follow_redirects=False,
    )
    assert login.status_code in (303, 302), login.text
    # Multi-tenant seed → pick alfa
    sel = client.post(
        "/orgs/seleccionar",
        data={"organization_id": world["alfa"]["organization_id"], "next": "/productores"},
        follow_redirects=False,
    )
    assert sel.status_code in (303, 302), sel.text
    r = client.get("/productores")
    assert r.status_code == 200
    assert "Productores" in r.text
    create = client.post(
        "/productores",
        data={
            "first_name": "Luis",
            "last_name": "Prod",
            "email": "luis.f4@example.invalid",
            "code": "LUIS",
        },
        follow_redirects=False,
    )
    assert create.status_code == 303
    loc = create.headers["location"]
    assert "/productores/" in loc
    profile_path = loc.split("?")[0]
    detail = client.get(profile_path)
    assert detail.status_code == 200
    assert "Luis" in detail.text
    assign = client.post(
        f"{profile_path}/asignar",
        data={
            "policy_id": world["alfa"]["policy_id"],
            "reason": "asignación F4 test",
        },
        follow_redirects=False,
    )
    assert assign.status_code == 303
    hist = client.get(f"/polizas/{world['alfa']['policy_id']}/productor")
    assert hist.status_code == 200
    assert "Historial" in hist.text
    assert "asignación F4 test" in hist.text
