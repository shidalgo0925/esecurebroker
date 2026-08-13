"""Datos bancarios públicos para pago SaaS (transferencia / Yappy)."""

from __future__ import annotations

# Cuenta receptora ESecureBroker — visible en checkout.
SAAS_BANK = {
    "bank": "Banistmo",
    "account_type": "Cuenta de Ahorros",
    "account_number": "4160224532",
    "yappy_name": "Seúl N. Hidalgo R.",
    "yappy_phone": "6184-2170",
}


def bank_details_for_checkout() -> dict[str, str]:
    return dict(SAAS_BANK)
