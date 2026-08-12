"""Cliente M2M ESB → EN1 (ADR-006 Ana).

SoR comercial = EN1. Este módulo NO simula respuestas exitosas ni inventa
ledger/entitlements locales. Sin contrato CODITO + base URL + token, falla cerrado.

Paths provisionales: se reemplazan cuando CODITO entregue el contrato oficial.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from corredores.services.runtime_settings import runtime

log = logging.getLogger(__name__)

# Paths provisionales — NO definitivos hasta contrato CODITO/ANA.
_PROVISIONAL = {
    "identity": "/api/v1/esb/commerce/identity",
    "intent": "/api/v1/esb/commerce/intent",
    "promo_payment": "/api/v1/esb/commerce/promo-payment",
    "activate": "/api/v1/esb/commerce/activate",
    "entitlements": "/api/v1/esb/commerce/entitlements",
}


class En1CommerceError(Exception):
    """Error de comercio EN1 (mensaje seguro para UX vía str o .user_message)."""

    def __init__(self, message: str, *, user_message: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.user_message = user_message or (
            "No pudimos completar la activación de tu cuenta. "
            "Puedes volver a intentarlo sin realizar un segundo pago."
        )
        self.status_code = status_code


class En1CommerceNotConfigured(En1CommerceError):
    def __init__(self) -> None:
        super().__init__(
            "EN1 commerce M2M not configured",
            user_message=(
                "El comercio con EN1 aún no está disponible en este entorno. "
                "Intenta más tarde o contacta soporte."
            ),
            status_code=503,
        )


@dataclass(frozen=True)
class En1IdentityResult:
    subject_id: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class En1CommercialIntent:
    organization_id: str
    subscription_id: str
    customer_id: str | None
    plan_code: str
    list_price: str | None
    currency: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class En1PromoPaymentResult:
    payment_id: str
    subscription_id: str
    status: str
    original_amount: str
    discount_amount: str
    final_amount: str
    promo_code: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class En1ActivationResult:
    subscription_id: str
    status: str
    entitlements: list[Any]
    seats: int | None
    raw: dict[str, Any]


def en1_commerce_enabled() -> bool:
    return runtime().bool("saas.en1_commerce_enabled", False)


def _base_and_token() -> tuple[str, str]:
    base = (runtime().get("saas.en1_api_base_url") or "").strip().rstrip("/")
    token = (runtime().get("saas.en1_m2m_token") or "").strip()
    if not base or not token:
        raise En1CommerceNotConfigured()
    # Guardrail: ESB DEV never points at EN1 PROD
    from corredores.config import settings

    if settings.app_env.strip().lower() in {"dev", "test", "local"}:
        if "appprd" in base.lower():
            raise En1CommerceError(
                "refusing EN1 PROD base from ESB DEV",
                user_message="Configuración inválida del entorno. Contacta soporte.",
                status_code=503,
            )
    return base, token


def new_correlation_id() -> str:
    return str(uuid.uuid4())


class En1CommercialClient:
    """HTTP M2M. Fail-closed: never fabricates ACTIVE subscription/payment."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        base, token = _base_and_token()
        url = f"{base}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Correlation-Id": correlation_id,
            "X-ESB-Product": "esecurebroker",
            "X-ESB-Environment": __import__("corredores.config", fromlist=["settings"]).settings.app_env,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.request(method, url, json=json_body, headers=headers)
        except httpx.HTTPError as e:
            log.exception("en1_commerce_transport correlation_id=%s error=%s", correlation_id, e)
            raise En1CommerceError(f"transport: {e}") from e

        if resp.status_code >= 400:
            log.error(
                "en1_commerce_http correlation_id=%s status=%s body=%s",
                correlation_id,
                resp.status_code,
                (resp.text or "")[:500],
            )
            raise En1CommerceError(
                f"EN1 HTTP {resp.status_code}",
                status_code=resp.status_code,
            )
        if not resp.content:
            return {}
        try:
            data = resp.json()
        except ValueError as e:
            raise En1CommerceError("invalid JSON from EN1") from e
        if not isinstance(data, dict):
            raise En1CommerceError("unexpected EN1 payload")
        return data

    def resolve_or_create_identity(
        self,
        *,
        email: str,
        display_name: str,
        phone: str | None = None,
        correlation_id: str,
        idempotency_key: str,
    ) -> En1IdentityResult:
        data = self._request(
            "POST",
            _PROVISIONAL["identity"],
            json_body={
                "email": email,
                "display_name": display_name,
                "phone": phone,
                "product": "esecurebroker",
            },
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        subject_id = data.get("subject_id") or data.get("id")
        if not subject_id:
            raise En1CommerceError("EN1 identity response missing subject_id")
        return En1IdentityResult(subject_id=str(subject_id), raw=data)

    def create_commercial_intent(
        self,
        *,
        subject_id: str,
        org_name: str,
        tax_id: str | None,
        plan_code: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> En1CommercialIntent:
        data = self._request(
            "POST",
            _PROVISIONAL["intent"],
            json_body={
                "subject_id": subject_id,
                "organization_name": org_name,
                "tax_id": tax_id,
                "product": "esecurebroker",
                "plan_code": plan_code,
            },
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        org_id = data.get("organization_id")
        sub_id = data.get("subscription_id")
        if not org_id or not sub_id:
            raise En1CommerceError("EN1 intent missing organization_id/subscription_id")
        return En1CommercialIntent(
            organization_id=str(org_id),
            subscription_id=str(sub_id),
            customer_id=str(data["customer_id"]) if data.get("customer_id") else None,
            plan_code=str(data.get("plan_code") or plan_code),
            list_price=str(data["list_price"]) if data.get("list_price") is not None else None,
            currency=str(data.get("currency") or "USD"),
            raw=data,
        )

    def validate_promo_and_record_payment(
        self,
        *,
        subscription_id: str,
        organization_id: str,
        promo_code: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> En1PromoPaymentResult:
        """Validate promo + record payment (incl. $0 PROMO). No local bypass."""
        data = self._request(
            "POST",
            _PROVISIONAL["promo_payment"],
            json_body={
                "subscription_id": subscription_id,
                "organization_id": organization_id,
                "product": "esecurebroker",
                "promo_code": promo_code.strip(),
                "payment_method": "PROMO",
            },
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        payment_id = data.get("payment_id")
        status = (data.get("status") or "").upper()
        if not payment_id or status not in {"COMPLETED", "COMPLETE", "PAID", "SUCCESS"}:
            raise En1CommerceError(
                f"EN1 promo payment not completed: status={status!r}",
            )
        return En1PromoPaymentResult(
            payment_id=str(payment_id),
            subscription_id=str(data.get("subscription_id") or subscription_id),
            status=status,
            original_amount=str(data.get("original_amount", "")),
            discount_amount=str(data.get("discount_amount", "")),
            final_amount=str(data.get("final_amount", "0")),
            promo_code=str(data.get("promo_code") or promo_code),
            raw=data,
        )

    def activate_subscription(
        self,
        *,
        subscription_id: str,
        payment_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> En1ActivationResult:
        data = self._request(
            "POST",
            _PROVISIONAL["activate"],
            json_body={
                "subscription_id": subscription_id,
                "payment_id": payment_id,
                "product": "esecurebroker",
            },
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        status = (data.get("status") or data.get("subscription_status") or "").upper()
        if status not in {"ACTIVE", "TRIALING"}:
            raise En1CommerceError(f"EN1 subscription not active: {status!r}")
        ents = data.get("entitlements") or []
        if not isinstance(ents, list):
            ents = []
        seats = data.get("seats")
        return En1ActivationResult(
            subscription_id=str(data.get("subscription_id") or subscription_id),
            status=status,
            entitlements=ents,
            seats=int(seats) if seats is not None else None,
            raw=data,
        )

    def get_entitlements(
        self, *, organization_id: str, correlation_id: str
    ) -> dict[str, Any]:
        path = f"{_PROVISIONAL['entitlements']}?organization_id={organization_id}&product=esecurebroker"
        return self._request("GET", path, correlation_id=correlation_id)
