"""ADR-006: CTAs locales + comercio EN1 C1 fail-closed (sin simular SoR)."""

from __future__ import annotations

import pytest

from corredores.services.en1_commercial import (
    En1CommercialClient,
    En1CommerceNotConfigured,
    en1_plan_code,
)
from corredores.services.saas_plans import start_href


def test_start_href_is_local_registro():
    assert start_href("oficina") == "/registro?plan=oficina"
    assert start_href("individual") == "/registro?plan=individual"
    assert start_href("enterprise") == "/#contacto"


def test_en1_plan_code_mapping():
    assert en1_plan_code("individual") == "individual"
    assert en1_plan_code("oficina") == "office"
    assert en1_plan_code("broker_red") == "broker"
    assert en1_plan_code("office") == "office"


def test_en1_client_fail_closed_without_config(monkeypatch):
    from corredores.services import runtime_settings as rs

    monkeypatch.setattr(
        rs,
        "runtime",
        lambda: rs.RuntimeConfig(
            {
                "saas.en1_commerce_enabled": "true",
                "saas.en1_api_base_url": "",
                "saas.en1_m2m_token": "",
            }
        ),
    )
    client = En1CommercialClient()
    with pytest.raises(En1CommerceNotConfigured):
        client.bootstrap(
            email="a@b.invalid",
            full_name="A",
            organization_name="Org",
            plan_code="individual",
            correlation_id="c1",
            idempotency_key="k1",
        )


def test_en1_client_refuses_prod_base_from_dev(monkeypatch):
    from corredores.config import settings
    from corredores.services import runtime_settings as rs
    from corredores.services.en1_commercial import En1CommerceError

    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(
        rs,
        "runtime",
        lambda: rs.RuntimeConfig(
            {
                "saas.en1_api_base_url": "https://appprd.easynodeone.com",
                "saas.en1_m2m_token": "tok",
            }
        ),
    )
    client = En1CommercialClient()
    with pytest.raises(En1CommerceError):
        client.bootstrap(
            email="a@b.invalid",
            full_name="A",
            organization_name="Org",
            plan_code="individual",
            correlation_id="c1",
            idempotency_key="k1",
        )


def test_en1_request_uses_x_api_key(monkeypatch):
    from corredores.services import runtime_settings as rs
    from corredores.services import en1_commercial as mod

    cfg = rs.RuntimeConfig(
        {
            "saas.en1_api_base_url": "https://appdev.easynodeone.com",
            "saas.en1_m2m_token": "test-key-material",
        }
    )
    monkeypatch.setattr(mod, "runtime", lambda: cfg)

    captured: dict = {}

    class _Resp:
        status_code = 200
        content = b"{}"
        text = "{}"

        def json(self):
            return {
                "product_code": "esecurebroker",
                "plan_code": "individual",
                "identity": {"user_id": 1, "email": "a@b.invalid", "created": True},
                "customer_id": 9,
                "contract_id": 8,
                "provider_organization_id": 1,
            }

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, url, json=None, headers=None, params=None):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            captured["params"] = params
            return _Resp()

    monkeypatch.setattr(mod.httpx, "Client", _Client)
    client = En1CommercialClient()
    out = client.bootstrap(
        email="a@b.invalid",
        full_name="A",
        organization_name="Org A",
        plan_code="individual",
        correlation_id="c1",
        idempotency_key="idem-1",
    )
    assert out.customer_id == "9"
    assert captured["headers"]["X-API-Key"] == "test-key-material"
    assert captured["headers"]["Idempotency-Key"] == "idem-1"
    assert "Authorization" not in captured["headers"]
    assert captured["json"]["plan_code"] == "individual"
    assert "/api/v1/commercial/bootstrap" in captured["url"]
