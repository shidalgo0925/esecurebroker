"""Self-serve landing → registro → checkout piloto."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.models import BrokerAccount, OrgSubscription
from corredores.services.auto_e2e import run_auto_e2e_demo
from corredores.services.seed_pilot import seed_pilot
from corredores.web import create_app


def setup_module():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as session:
        seed_pilot(session)
        run_auto_e2e_demo(session, today=date(2026, 8, 10))
        session.commit()


def test_landing_shows_plans():
    client = TestClient(create_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "ESecure" in r.text
    assert "bajo control" in r.text
    assert "Empieza el día sabiendo" in r.text
    assert "Individual" in r.text
    assert "Oficina" in r.text
    assert "Broker / Red" in r.text
    assert "Enterprise" in r.text
    assert "A medida" in r.text
    assert "Trabajo por mi cuenta" in r.text
    assert "/registro?plan=oficina" in r.text
    assert "appdev.easynodeone.com" not in r.text
    assert "appprd.easynodeone.com" not in r.text
    assert "/#contacto" in r.text or "Hablar con ventas" in r.text


def test_register_and_piloto_checkout_reaches_hoy():
    client = TestClient(create_app())
    email = "nuevo.broker@example.invalid"
    reg = client.post(
        "/registro",
        data={
            "email": email,
            "password": "secreto123",
            "display_name": "Ana Broker",
            "org_name": "Correduría Ana",
            "plan": "oficina",
        },
        follow_redirects=False,
    )
    assert reg.status_code == 303, reg.text
    assert "/checkout" in reg.headers["location"]

    with db.SessionLocal() as session:
        acc = session.query(BrokerAccount).filter_by(email=email).one()
        assert acc.display_name == "Ana Broker"
        sub = session.query(OrgSubscription).filter_by(status="pending").all()
        assert any(s.plan_code == "oficina" for s in sub)

    pay = client.post(
        "/checkout",
        data={"plan": "oficina"},
        follow_redirects=False,
    )
    assert pay.status_code == 303
    assert "/checkout/success" in pay.headers["location"]

    with db.SessionLocal() as session:
        sub = (
            session.query(OrgSubscription)
            .join(_models.Organization)
            .filter(_models.Organization.name == "Correduría Ana")
            .one()
        )
        assert sub.status == "active"

    hoy = client.get("/hoy", follow_redirects=False)
    assert hoy.status_code == 200
    assert "Hoy" in hoy.text or "hoy" in hoy.text.lower() or "ESecure" in hoy.text


def test_login_with_registered_email():
    client = TestClient(create_app())
    email = "login.broker@example.invalid"
    client.post(
        "/registro",
        data={
            "email": email,
            "password": "secreto123",
            "display_name": "Luis",
            "org_name": "Luis Corredores",
            "plan": "individual",
        },
        follow_redirects=False,
    )
    client.post("/checkout", data={"plan": "individual"}, follow_redirects=False)
    client.cookies.clear()

    login = client.post(
        "/login",
        data={"username": email, "password": "secreto123", "next": "/hoy"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/hoy"


def test_pending_user_can_change_plan_from_checkout():
    """Bug: 'Cambiar de plan' → / → /hoy → checkout mismo plan (atrapado)."""
    client = TestClient(create_app())
    email = "cambia.plan@example.invalid"
    client.post(
        "/registro",
        data={
            "email": email,
            "password": "secreto123",
            "display_name": "Cambia Plan",
            "org_name": "Org Cambia Plan",
            "plan": "oficina",
        },
        follow_redirects=False,
    )

    land = client.get("/", follow_redirects=False)
    assert land.status_code == 200
    assert "/registro?plan=individual" in land.text
    assert "Individual" in land.text

    switch = client.get("/checkout?plan=individual", follow_redirects=False)
    assert switch.status_code == 200
    assert "Individual" in switch.text
    assert 'name="plan" value="individual"' in switch.text
    assert "/checkout?plan=oficina" in switch.text  # alt switcher

    with db.SessionLocal() as session:
        sub = (
            session.query(OrgSubscription)
            .join(_models.Organization)
            .filter(_models.Organization.name == "Org Cambia Plan")
            .one()
        )
        assert sub.status == "pending"
        assert sub.plan_code == "individual"


def test_legacy_plan_alias_profesional_maps_to_oficina():
    from corredores.services.saas_plans import require_plan

    assert require_plan("profesional").code == "oficina"
    assert require_plan("esencial").code == "individual"
