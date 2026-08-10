"""Piloto UI smoke — FastAPI TestClient over domain services."""

from datetime import date
import re

from fastapi.testclient import TestClient

import corredores.db as db
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


def test_piloto_surfaces_ok():
    client = TestClient(create_app())
    for path in (
        "/hoy",
        "/radar",
        "/clientes",
        "/polizas",
        "/polizas/nueva",
        "/cobranza",
        "/cotizador",
        "/renovaciones",
        "/reclamos",
        "/oportunidades",
        "/aseguradoras",
        "/ayuda",
    ):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "ESecureBroker" in r.text
        assert "sidebar" in r.text or "Nueva gestión" in r.text

    shell = client.get("/hoy")
    assert "+ Nueva gestión" in shell.text
    assert "Pólizas" in shell.text
    assert "Cartera" in shell.text
    assert "Estudio 360" not in shell.text  # not a primary nav item
    assert "EN1 stub" not in shell.text
    assert "IA recomienda" not in shell.text
    assert "Requiere tu atención" in shell.text

    polizas = client.get("/polizas")
    assert "+ Nueva póliza" in polizas.text

    parties = client.get("/clientes")
    m = re.search(r'href="/clientes/([0-9a-f-]{36})"', parties.text)
    assert m
    c360 = client.get(f"/clientes/{m.group(1)}")
    assert c360.status_code == 200
    assert "Generar estudio 360°" in c360.text
