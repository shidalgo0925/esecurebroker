"""PaymentService — interfaz común; no mete lógica de proveedor en routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from corredores.domain.models import Organization, OrgSubscription
from corredores.services.en1_commercial import (
    En1CommercialClient,
    En1CommerceError,
    DEV_PROMO_CODE,
    new_correlation_id,
)
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
    checkout_raw: dict[str, Any] | None = None
    entitlement_raw: dict[str, Any] | None = None


class PaymentService:
    def __init__(self, client: En1CommercialClient | None = None) -> None:
        self._client = client or En1CommercialClient()

    def process_promo_activation(
        self,
        db: Session,
        *,
        organization: Organization,
        local_subscription: OrgSubscription,
        promo_code: str,
        en1_customer_id: str | None = None,
        en1_subscription_id: str | None = None,
        en1_organization_id: str | None = None,
    ) -> PaymentResult:
        """
        C1: checkout (promo → $0 → ACTIVE) → entitlement → mirror local ACTIVE.
        Fail-closed: sin bypass piloto.
        """
        del en1_organization_id, en1_subscription_id  # legacy kwargs ignored
        correlation_id = new_correlation_id()
        customer_id = (
            en1_customer_id
            or (local_subscription.stripe_customer_id or "").strip()
            or (organization.external_en1_org_id or "").strip()
        )
        if local_subscription.billing_provider != "en1":
            # Still allow if ids present (re-try after partial)
            pass
        if not customer_id:
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
                error_detail="missing en1 customer_id",
            )
        promo = (promo_code or "").strip() or DEV_PROMO_CODE

        try:
            checkout = self._client.checkout(
                customer_id=customer_id,
                plan_code=local_subscription.plan_code,
                promo_code=promo,
                correlation_id=correlation_id,
                idempotency_key=f"esb:checkout:{customer_id}:{promo.upper()}:{local_subscription.plan_code}",
            )
            entitlement = self._client.get_entitlement(
                customer_id=customer_id,
                correlation_id=correlation_id,
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

        if not entitlement.entitled:
            return PaymentResult(
                ok=False,
                correlation_id=correlation_id,
                payment_id=None,
                subscription_status=checkout.subscription_status,
                entitlements=[],
                user_message=(
                    "EN1 no confirmó el entitlement. No activamos la cuenta local. "
                    "Puedes reintentar sin un segundo pago."
                ),
                error_detail=f"entitled=false state={entitlement.state}",
                checkout_raw=checkout.raw,
                entitlement_raw=entitlement.raw,
            )

        activate_subscription(
            db,
            local_subscription,
            provider="en1",
            stripe_customer_id=customer_id,
            stripe_subscription_id=checkout.subscription_id,
            stripe_checkout_session_id=checkout.promo_code,
        )
        if entitlement.plan_code:
            # Keep ESB canonical if possible; store EN1 plan only when already ESB-shaped.
            if entitlement.plan_code in {"individual", "oficina", "broker_red", "enterprise"}:
                local_subscription.plan_code = entitlement.plan_code
            elif entitlement.plan_code == "office":
                local_subscription.plan_code = "oficina"
            elif entitlement.plan_code == "broker":
                local_subscription.plan_code = "broker_red"
        from corredores.services.seats import persist_en1_seat_limits

        persist_en1_seat_limits(db, local_subscription, entitlement.limits)
        db.flush()
        return PaymentResult(
            ok=True,
            correlation_id=correlation_id,
            payment_id=checkout.subscription_id,
            subscription_status=checkout.subscription_status,
            entitlements=[entitlement.raw],
            checkout_raw=checkout.raw,
            entitlement_raw=entitlement.raw,
        )
