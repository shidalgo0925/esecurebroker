"""ADR-007 — Organization A must not access Organization B resources."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import corredores.db as db
from corredores.config import settings
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.models import Party, Policy
from corredores.services.account_cxc import build_account_statement
from corredores.services.client_360 import build_client_360
from corredores.services.seed_tenants import seed_multitenant_demo
from corredores.services.tenant import require_org_owned
from corredores.web import create_app
from corredores.web.auth_session import actor_id_for_username


@pytest.fixture()
def tenants(monkeypatch):
    monkeypatch.setattr(
        settings,
        "auth_users",
        "broker-a:pass-a|broker-b:pass-b|broker-multi:pass-m",
    )
    monkeypatch.setattr(settings, "auth_enabled", True)
    if not (settings.auth_secret or "").strip():
        monkeypatch.setattr(settings, "auth_secret", "test-secret-adr007-isolation")

    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as session:
        report = seed_multitenant_demo(session, today=date(2026, 8, 10))
        session.commit()
    return report


def test_require_org_owned_blocks_cross_tenant(tenants):
    with db.SessionLocal() as session:
        with pytest.raises(HTTPException) as ei:
            require_org_owned(
                session,
                Party,
                tenants["beta"]["party_id"],
                tenants["alfa"]["organization_id"],
            )
        assert ei.value.status_code == 404

        with pytest.raises(HTTPException) as ei2:
            require_org_owned(
                session,
                Policy,
                tenants["alfa"]["policy_id"],
                tenants["beta"]["organization_id"],
            )
        assert ei2.value.status_code == 404

        own = require_org_owned(
            session,
            Party,
            tenants["alfa"]["party_id"],
            tenants["alfa"]["organization_id"],
        )
        assert own.id == tenants["alfa"]["party_id"]


def test_services_scope_by_organization(tenants):
    with db.SessionLocal() as session:
        snap_a = build_client_360(
            session, tenants["alfa"]["organization_id"], tenants["alfa"]["party_id"]
        )
        assert snap_a is not None
        with pytest.raises(ValueError):
            build_client_360(
                session, tenants["alfa"]["organization_id"], tenants["beta"]["party_id"]
            )

        stmt = build_account_statement(
            session, tenants["alfa"]["organization_id"], tenants["alfa"]["party_id"]
        )
        assert stmt.party_id == tenants["alfa"]["party_id"]
        with pytest.raises(ValueError):
            build_account_statement(
                session, tenants["alfa"]["organization_id"], tenants["beta"]["party_id"]
            )


def test_http_user_a_cannot_open_party_b(tenants):
    client = TestClient(create_app())
    login = client.post(
        "/login",
        data={"username": "broker-a", "password": "pass-a", "next": "/hoy"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers.get("location") == "/hoy"

    own = client.get(f"/clientes/{tenants['alfa']['party_id']}")
    assert own.status_code == 200
    assert "Demo" in own.text or "Cliente" in own.text

    foreign = client.get(f"/clientes/{tenants['beta']['party_id']}")
    assert foreign.status_code == 404

    foreign_pol = client.get(f"/polizas/{tenants['beta']['policy_id']}")
    assert foreign_pol.status_code == 404

    client_b = TestClient(create_app())
    login_b = client_b.post(
        "/login",
        data={"username": "broker-b", "password": "pass-b", "next": "/hoy"},
        follow_redirects=False,
    )
    assert login_b.status_code == 303
    own_b = client_b.get(f"/clientes/{tenants['beta']['party_id']}")
    assert own_b.status_code == 200
    leak = client_b.get(f"/clientes/{tenants['alfa']['party_id']}")
    assert leak.status_code == 404


def test_membership_subject_bound(tenants):
    assert actor_id_for_username("broker-a") == "piloto:broker-a"
    with db.SessionLocal() as session:
        from corredores.services.tenant import list_memberships

        ms = list_memberships(session, "piloto:broker-a")
        assert len(ms) == 1
        assert ms[0].organization_id == tenants["alfa"]["organization_id"]
        ms_m = list_memberships(session, "piloto:broker-multi")
        assert len(ms_m) == 2
