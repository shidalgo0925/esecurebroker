"""Piloto UI smoke — FastAPI TestClient over domain services."""

from datetime import date

from fastapi.testclient import TestClient

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.services.auto_e2e import run_auto_e2e_demo
from corredores.web import create_app


def setup_module():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as session:
        run_auto_e2e_demo(session, today=date(2026, 8, 10))
        session.commit()


def test_piloto_surfaces_ok():
    client = TestClient(create_app())
    for path in (
        "/hoy",
        "/radar",
        "/clientes",
        "/cobranza",
        "/cotizador",
        "/renovaciones",
        "/reclamos",
        "/ayuda",
    ):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "ESecureBroker" in r.text

    ayuda = client.get("/ayuda")
    assert "Captura" in ayuda.text
    assert "Comparador" in ayuda.text
    assert "Rutinario" in ayuda.text or "intervención" in ayuda.text.lower()
    parties = client.get("/clientes")
    assert parties.status_code == 200
    # follow first 360 link if present
    if "/clientes/" in parties.text:
        # extract a uuid-looking href
        import re

        m = re.search(r'href="/clientes/([0-9a-f-]{36})"', parties.text)
        assert m
        c360 = client.get(f"/clientes/{m.group(1)}")
        assert c360.status_code == 200
        assert "360" in c360.text
