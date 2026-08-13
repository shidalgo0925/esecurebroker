"""ADR-011 F4 — CRM Pipeline Web / Kanban HTML."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.membership_roles import OWNER
from corredores.domain.models import BrokerAccount, OrgSubscription
from corredores.services.crm_catalog_seed import ensure_default_crm_catalogs
from corredores.services.crm_service import (
    create_opportunity,
    create_prospect,
    list_opportunities,
    set_opportunity_stage,
)
from corredores.services.saas_signup import hash_password
from corredores.services.seed_tenants import seed_multitenant_demo
from corredores.services.tenant import ensure_membership
from corredores.config import settings
from corredores.web import create_app
from corredores.web.auth_session import actor_id_for_username
from corredores.services.access_control import resolve_access_context


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
    ensure_default_crm_catalogs(session, org)
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
    return {"org": org, "email": owner_email, "subject": owner_subj}


def test_pipeline_flow_service_layer(session, world):
    ctx = resolve_access_context(
        session,
        subject_id=world["subject"],
        organization_id=world["org"],
        username=world["email"],
    )
    p = create_prospect(
        session,
        ctx,
        organization_id=world["org"],
        first_name="Ana",
        last_name="Lead",
        email="ana.f4@example.invalid",
        actor_id=world["subject"],
    )
    opp = create_opportunity(
        session,
        ctx,
        organization_id=world["org"],
        title="Auto Ana",
        prospect_id=p.id,
        estimated_premium=Decimal("1200.00"),
        actor_id=world["subject"],
    )
    set_opportunity_stage(
        session,
        ctx,
        organization_id=world["org"],
        opportunity_id=opp.id,
        stage_code="CONTACTED",
        actor_id=world["subject"],
    )
    session.commit()
    open_opps = list_opportunities(session, ctx, world["org"], include_lost=False)
    assert any(o.id == opp.id and o.stage_code == "CONTACTED" for o in open_opps)


def test_crm_html_routes(session, world, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    client = TestClient(create_app())
    r = client.get("/crm")
    assert r.status_code == 200
    assert b"Pipeline CRM" in r.content
    r2 = client.get("/crm/prospectos")
    assert r2.status_code == 200
    assert b"Nuevo prospecto" in r2.content
    # create via form
    r3 = client.post(
        "/crm/prospectos",
        data={
            "prospect_type": "PERSON",
            "first_name": "Luis",
            "last_name": "Web",
            "email": "luis.f4@example.invalid",
            "phone": "6000-1111",
        },
        follow_redirects=False,
    )
    assert r3.status_code == 303
    assert "/crm/prospectos/" in r3.headers.get("location", "")
