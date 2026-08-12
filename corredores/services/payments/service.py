"""PaymentService — interfaz común; no mete lógica de proveedor en routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from corredores.domain.models import Organization, OrgSubscription
from corredores.services.en1_commercial import (
    En1ActivationResult,
    En1CommercialClient,
    En1CommerceError,
    new_correlation_id,
)
from corredores.services.payments.providers.promo import PromoCodeProvider
from corredores.services.saas_signup import activate_subscription


@dataclass(frozen=True)
class PaymentResult:
    ok: bool
    correlation_id: str
    payment_id: str | None
    subscription_status: str | None
    entitlements: list[Any]
    user_message: str | None = None
    error_detail: str | None = None


class PaymentService:
    def __init__(self, client: En1CommercialClient | None = None) -> None:
        self._client = client or En1CommercialClient()
        self._promo = PromoCodeProvider(self._client)

    def process_promo_activation(
        self,
        db: Session,
        *,
        organization: Organization,
        local_subscription: OrgSubscription,
        promo_code: str,
        en1_subscription_id: str | None = None,
        en1_organization_id: str | None = None,
    ) -> PaymentResult:
        """
        Promo → EN1 payment ($0 OK con ledger) → activate → mirror local ACTIVE.
        Requiere ids EN1 en org/sub o parámetros explícitos.
        """
        correlation_id = new_correlation_id()
        en1_org = (en1_organization_id or organization.external_en1_org_id or "").strip()
        en1_sub = (en1_subscription_id or getattr(local_subscription, "external_en1_subscription_id", None) or "").strip()
        # Until migration adds column, allow stripe_checkout_session_id reuse? Better store in billing_provider metadata.
        # Use organization.external_en1_org_id + plan intent id stored in stripe_subscription_id temporarily? Ugly.
        # For M1 scaffolding: read from local_subscription.stripe_subscription_id if provider is en1.
        if not en1_sub and local_subscription.billing_provider == "en1":
            en1_sub = (local_subscription.stripe_subscription_id or "").strip()
        if not en1_org or not en1_sub:
            return PaymentResult(
                ok=False,
                correlation_id=correlation_id,
                payment_id=None,
                subscription_status=None,
                entitlements=[],
                user_message=(
                    "Falta vinculación comercial con EN1. Completa el registro de nuevo "
                    "cuando el comercio EN1 esté disponible."
                ),
                error_detail="missing en1 org/subscription ids",
            )
        if not (promo_code or "").strip():
            return PaymentResult(
                ok=False,
                correlation_id=correlation_id,
                payment_id=None,
                subscription_status=None,
                entitlements=[],
                user_message="Ingresa un código promocional válido.",
                error_detail="empty promo",
            )

        try:
            charge = self._promo.charge(
                subscription_id=en1_sub,
                organization_id=en1_org,
                promo_code=promo_code.strip(),
                correlation_id=correlation_id,
                idempotency_key=f"promo-pay:{en1_sub}:{promo_code.strip().upper()}",
            )
            activation: En1ActivationResult = self._client.activate_subscription(
                subscription_id=en1_sub,
                payment_id=charge.payment_id or "",
                correlation_id=correlation_id,
                idempotency_key=f"activate:{en1_sub}:{charge.payment_id}",
            )
        except En1CommerceError as e:
            return PaymentResult(
                ok=False,
                correlation_id=correlation_id,
                payment_id=None,
                subscription_status=None,
                entitlements=[],
                user_message=e.user_message,
                error_detail=str(e),
            )

        activate_subscription(
            db,
            local_subscription,
            provider="en1",
            stripe_customer_id=en1_org,
            stripe_subscription_id=en1_sub,
            stripe_checkout_session_id=charge.payment_id,
        )
        local_subscription.plan_code = local_subscription.plan_code
        db.flush()
        return PaymentResult(
            ok=True,
            correlation_id=correlation_id,
            payment_id=charge.payment_id,
            subscription_status=activation.status,
            entitlements=list(activation.entitlements),
        )
