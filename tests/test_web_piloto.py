"""Piloto UI smoke — FastAPI TestClient over domain services."""

from datetime import date
import re

from fastapi.testclient import TestClient

import corredores.db as db
from corredores.config import settings
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
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


def _authed_client() -> TestClient:
    client = TestClient(create_app())
    if settings.auth_enabled:
        r = client.post(
            "/login",
            data={
                "username": settings.auth_username,
                "password": settings.auth_password,
                "next": "/hoy",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303, r.text
        assert r.headers.get("location") == "/hoy", r.headers.get("location")
        assert settings.auth_cookie_name in client.cookies
    return client


def test_welcome_login_gate():
    client = TestClient(create_app())
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 200
    assert "ESecure" in root.text
    assert "Tu correduría, bajo control" in root.text

    welcome = client.get("/bienvenida", follow_redirects=False)
    assert welcome.status_code == 303
    assert welcome.headers["location"] in {"/", "/?next="} or welcome.headers["location"].startswith("/")

    login = client.get("/login")
    assert login.status_code == 200
    assert 'name="password"' in login.text

    if settings.auth_enabled:
        blocked = client.get("/hoy", follow_redirects=False)
        assert blocked.status_code == 303
        loc = blocked.headers["location"]
        assert loc.startswith("/") and ("bienvenida" in loc or loc.startswith("/?") or loc == "/" or "next=" in loc)


def test_piloto_surfaces_ok():
    client = _authed_client()
    for path in (
        "/hoy",
        "/radar",
        "/clientes",
        "/clientes/nuevo",
        "/polizas",
        "/polizas/nueva",
        "/cobranza",
        "/cobranza/pagos/nuevo",
        "/cotizador",
        "/renovaciones",
        "/reclamos",
        "/oportunidades",
        "/aseguradoras",
        "/ramos",
        "/comisiones",
        "/reportes",
        "/ayuda",
    ):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "ESecureBroker" in r.text
        assert "sidebar" in r.text or "Nueva gestión" in r.text

    shell = client.get("/hoy")
    assert "+ Nueva gestión" in shell.text or "Nueva gestión" in shell.text
    assert "Pólizas" in shell.text
    assert "Cartera" in shell.text
    assert "Estudio 360" not in shell.text  # not a primary nav item
    assert "EN1 stub" not in shell.text
    assert "IA recomienda" not in shell.text
    assert "Requiere tu atención" in shell.text
    assert "nav-ico" in shell.text or "viewBox" in shell.text  # SVG icons
    assert "Expediente del día" in shell.text or "ledger" in shell.text or "stamp" in shell.text or "dossier" in shell.text
    assert 'id="nuevaGestion"' in shell.text
    assert 'nueva-gestion" id="nuevaGestion" open' not in shell.text  # starts collapsed by default
    assert "Salir" in shell.text

    filtered = client.get("/clientes?q=Demo")
    assert filtered.status_code == 200
    assert "filter-bar" in filtered.text

    cob_f = client.get("/cobranza?estado=OVERDUE")
    assert cob_f.status_code == 200
    assert "filter-bar" in cob_f.text

    polizas = client.get("/polizas")
    assert "+ Nueva póliza" in polizas.text

    parties = client.get("/clientes")
    m = re.search(r'href="/clientes/([0-9a-f-]{36})"', parties.text)
    assert m
    c360 = client.get(f"/clientes/{m.group(1)}")
    assert c360.status_code == 200
    assert "Editar" in c360.text

    # Captura cliente + reportes CSV
    created = client.post(
        "/clientes/nuevo",
        data={
            "party_type": "PERSON",
            "first_name": "Ana",
            "last_name": "Prueba",
            "national_id": "8-CAPTURA-1",
            "phone": "6000-0000",
            "email": "",
            "district": "",
            "address": "",
            "birth_date": "",
            "legal_name": "",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert "/clientes/" in created.headers["location"]

    csv_r = client.get("/reportes/cartera.csv")
    assert csv_r.status_code == 200
    assert "policy_number" in csv_r.text

    cob = client.get("/cobranza")
    assert "Registrar pago" in cob.text or "Cobrar" in cob.text

    reports = client.get("/reportes")
    assert "SALDO ABIERTO" in reports.text or "Cartera de pólizas" in reports.text

    # PDF attachment on client 360
    party_loc = created.headers["location"]
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    up = client.post(
        f"{party_loc}/documentos",
        data={"title": "Cedula demo", "doc_kind": "CEDULA"},
        files={"file": ("cedula.pdf", pdf, "application/pdf")},
        follow_redirects=False,
    )
    assert up.status_code == 303, up.text
    c360b = client.get(party_loc)
    assert c360b.status_code == 200
    assert "Documentos PDF" in c360b.text
    assert "Cedula demo" in c360b.text or "cedula.pdf" in c360b.text
    docs_page = client.get("/documentos")
    assert docs_page.status_code == 200
    assert "filter-bar" in docs_page.text

    cap = client.get("/captura/poliza-foto")
    assert cap.status_code == 200
    assert "Captura desde foto" in cap.text
    assert "Dominio decide" in cap.text or "revisá" in cap.text.lower() or "Extraer" in cap.text
