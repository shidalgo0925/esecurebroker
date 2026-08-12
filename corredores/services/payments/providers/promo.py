"""PromoCodeProvider — Milestone 1. Delega validación+ledger a EN1 (sin bypass local)."""

from __future__ import annotations

from typing import Any

from corredores.services.en1_commercial import En1CommercialClient
from corredores.services.payments.providers.base import ProviderChargeResult


class PromoCodeProvider:
    method = "PROMO"

    def __init__(self, client: En1CommercialClient | None = None) -> None:
        self._client = client or En1CommercialClient()

    def charge(
        self,
        *,
        subscription_id: str,
        organization_id: str,
        promo_code: str,
        correlation_id: str,
        idempotency_key: str,
        **_: Any,
    ) -> ProviderChargeResult:
        result = self._client.validate_promo_and_record_payment(
            subscription_id=subscription_id,
            organization_id=organization_id,
            promo_code=promo_code,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return ProviderChargeResult(
            ok=True,
            payment_id=result.payment_id,
            status=result.status,
            method=self.method,
            metadata={
                "original_amount": result.original_amount,
                "discount_amount": result.discount_amount,
                "final_amount": result.final_amount,
                "promo_code": result.promo_code,
                "subscription_id": result.subscription_id,
                "raw": result.raw,
            },
        )
