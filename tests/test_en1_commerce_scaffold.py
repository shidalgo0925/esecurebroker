"""ADR-006: CTAs locales + comercio EN1 fail-closed (sin simular SoR)."""

from __future__ import annotations

import pytest

from corredores.services.en1_commercial import (
    En1CommercialClient,
    En1CommerceNotConfigured,
)
from corredores.services.saas_plans import start_href


def test_start_href_is_local_registro():
    assert start_href("oficina") == "/registro?plan=oficina"
    assert start_href("individual") == "/registro?plan=individual"
    assert start_href("enterprise") == "/#contacto"


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
        client.resolve_or_create_identity(
            email="a@b.invalid",
            display_name="A",
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
        client.resolve_or_create_identity(
            email="a@b.invalid",
            display_name="A",
            correlation_id="c1",
            idempotency_key="k1",
        )
