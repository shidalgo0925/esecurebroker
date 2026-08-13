"""Cliente M2M ESB → EN1 commercial bridge C1 (ADR-006).

Contrato CODITO (EN1 develop):
  POST /api/v1/commercial/bootstrap
  POST /api/v1/commercial/checkout
  GET  /api/v1/commercial/entitlement

Auth: X-API-Key. SoR comercial = EN1. Fail-closed: nunca inventa ACTIVE/entitled.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from corredores.services.runtime_settings import runtime

log = logging.getLogger(__name__)

PRODUCT_CODE = "esecurebroker"
DEV_PROMO_CODE = "ESB-DEV-100"

_PATHS = {
    "bootstrap": "/api/v1/commercial/bootstrap",
    "checkout": "/api/v1/commercial/checkout",
    "entitlement": "/api/v1/commercial/entitlement",
}

# ESB plan codes → EN1 C1 plan codes (no starter).
_ESB_TO_EN1_PLAN = {
    "individual": "individual",
    "oficina": "office",
    "office": "office",
    "broker_red": "broker",
    "broker": "broker",
    "enterprise": "enterprise",
}


class En1CommerceError(Exception):
    """Error de comercio EN1 (mensaje seguro para UX vía str o .user_message)."""

    def __init__(
        self,
        message: str,
        *,
        user_message: str | None = None,
        status_code: int | None = None,
        error_code: str | None = None,
    ):
        super().__init__(message)
        self.user_message = user_message or (
            "No pudimos completar la activación de tu cuenta. "
            "Puedes volver a intentarlo sin realizar un segundo pago."
        )
        self.status_code = status_code
        self.error_code = error_code


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
class En1BootstrapResult:
    product_code: str
    plan_code: str
    user_id: str
    email: str
    customer_id: str
    contract_id: str
    contract_number: str | None
    provider_organization_id: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class En1CheckoutResult:
    product_code: str
    customer_id: str
    subscription_id: str
    subscription_status: str
    plan_code: str
    promo_code: str
    list_amount: str
    discount_amount: str
    final_amount: str
    currency: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class En1EntitlementResult:
    product_code: str
    customer_id: str
    entitled: bool
    state: str
    plan_code: str
    subscription_id: str | None
    limits: dict[str, Any]
    features: dict[str, Any]
    raw: dict[str, Any]


def en1_commerce_enabled() -> bool:
    return runtime().bool("saas.en1_commerce_enabled", False)


def en1_plan_code(esb_plan_code: str) -> str:
    raw = (esb_plan_code or "").strip().lower()
    return _ESB_TO_EN1_PLAN.get(raw, raw or "individual")


def _base_and_api_key() -> tuple[str, str]:
    base = (runtime().get("saas.en1_api_base_url") or "").strip().rstrip("/")
    api_key = (runtime().get("saas.en1_m2m_token") or "").strip()
    if not base or not api_key:
        raise En1CommerceNotConfigured()
    from corredores.config import settings

    if settings.app_env.strip().lower() in {"dev", "test", "local"}:
        if "appprd" in base.lower():
            raise En1CommerceError(
                "refusing EN1 PROD base from ESB DEV",
                user_message="Configuración inválida del entorno. Contacta soporte.",
                status_code=503,
            )
    return base, api_key


def new_correlation_id() -> str:
    return str(uuid.uuid4())


class En1CommercialClient:
    """HTTP M2M C1. Fail-closed: never fabricates ACTIVE subscription/payment."""

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
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        base, api_key = _base_and_api_key()
        url = f"{base}{path}"
        headers = {
            "X-API-Key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Correlation-Id": correlation_id,
            "X-ESB-Product": PRODUCT_CODE,
            "X-ESB-Environment": __import__("corredores.config", fromlist=["settings"]).settings.app_env,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.request(
                    method, url, json=json_body, headers=headers, params=query
                )
        except httpx.HTTPError as e:
            log.exception("en1_commerce_transport correlation_id=%s error=%s", correlation_id, e)
            raise En1CommerceError(f"transport: {e}") from e

        if resp.status_code >= 400:
            # Never log API key; body truncated for diagnosis only.
            log.error(
                "en1_commerce_http correlation_id=%s status=%s body=%s",
                correlation_id,
                resp.status_code,
                (resp.text or "")[:500],
            )
            err_code = None
            try:
                payload = resp.json()
                if isinstance(payload, dict):
                    err_code = payload.get("error")
            except Exception:
                payload = None
            raise En1CommerceError(
                f"EN1 HTTP {resp.status_code}" + (f" ({err_code})" if err_code else ""),
                status_code=resp.status_code,
                error_code=str(err_code) if err_code else None,
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

    def bootstrap(
        self,
        *,
        email: str,
        full_name: str,
        organization_name: str,
        plan_code: str,
        phone: str | None = None,
        country: str = "PA",
        external_subject_id: str | None = None,
        esb_organization_id: str | None = None,
        correlation_id: str,
        idempotency_key: str,
    ) -> En1BootstrapResult:
        en1_plan = en1_plan_code(plan_code)
        data = self._request(
            "POST",
            _PATHS["bootstrap"],
            json_body={
                "product_code": PRODUCT_CODE,
                "plan_code": en1_plan,
                "identity": {
                    "email": email,
                    "full_name": full_name,
                    "external_subject_id": external_subject_id,
                },
                "customer": {
                    "email": email,
                    "legal_name": organization_name or full_name,
                    "country": country,
                    "phone": phone,
                    "esb_organization_id": esb_organization_id,
                },
            },
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        identity = data.get("identity") or {}
        customer_id = data.get("customer_id")
        contract_id = data.get("contract_id")
        user_id = identity.get("user_id")
        if customer_id is None or contract_id is None or user_id is None:
            raise En1CommerceError("EN1 bootstrap missing customer_id/contract_id/user_id")
        return En1BootstrapResult(
            product_code=str(data.get("product_code") or PRODUCT_CODE),
            plan_code=str(data.get("plan_code") or en1_plan),
            user_id=str(user_id),
            email=str(identity.get("email") or email),
            customer_id=str(customer_id),
            contract_id=str(contract_id),
            contract_number=str(data["contract_number"]) if data.get("contract_number") else None,
            provider_organization_id=(
                str(data["provider_organization_id"])
                if data.get("provider_organization_id") is not None
                else None
            ),
            raw=data,
        )

    def checkout(
        self,
        *,
        customer_id: str,
        plan_code: str,
        promo_code: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> En1CheckoutResult:
        en1_plan = en1_plan_code(plan_code)
        promo = (promo_code or "").strip() or DEV_PROMO_CODE
        data = self._request(
            "POST",
            _PATHS["checkout"],
            json_body={
                "product_code": PRODUCT_CODE,
                "plan_code": en1_plan,
                "customer_id": int(customer_id) if str(customer_id).isdigit() else customer_id,
                "promo_code": promo,
                "payment": {"method": "promo_comp"},
            },
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        payment = data.get("payment") or {}
        status = (data.get("subscription_status") or "").lower()
        sub_id = data.get("subscription_id")
        if not sub_id or status not in {"active", "trialing", "trial"}:
            raise En1CommerceError(
                f"EN1 checkout subscription not active: status={status!r}",
            )
        return En1CheckoutResult(
            product_code=str(data.get("product_code") or PRODUCT_CODE),
            customer_id=str(data.get("customer_id") or customer_id),
            subscription_id=str(sub_id),
            subscription_status=status,
            plan_code=str(data.get("plan_code") or en1_plan),
            promo_code=str(data.get("promo_code") or promo),
            list_amount=str(payment.get("list_amount", "")),
            discount_amount=str(payment.get("discount_amount", "")),
            final_amount=str(payment.get("amount", payment.get("final_amount", ""))),
            currency=str(payment.get("currency") or "USD"),
            raw=data,
        )

    def get_entitlement(
        self,
        *,
        customer_id: str,
        correlation_id: str,
        product_code: str = PRODUCT_CODE,
    ) -> En1EntitlementResult:
        data = self._request(
            "GET",
            _PATHS["entitlement"],
            correlation_id=correlation_id,
            query={
                "product_code": product_code,
                "customer_id": str(customer_id),
            },
        )
        limits = data.get("limits") if isinstance(data.get("limits"), dict) else {}
        features = data.get("features") if isinstance(data.get("features"), dict) else {}
        return En1EntitlementResult(
            product_code=str(data.get("product_code") or product_code),
            customer_id=str(data.get("customer_id") or customer_id),
            entitled=bool(data.get("entitled")),
            state=str(data.get("state") or ""),
            plan_code=str(data.get("plan_code") or ""),
            subscription_id=str(data["subscription_id"]) if data.get("subscription_id") is not None else None,
            limits=limits,
            features=features,
            raw=data,
        )

    # --- Back-compat names used by older tests/callers (map to C1) ---

    def resolve_or_create_identity(
        self,
        *,
        email: str,
        display_name: str,
        phone: str | None = None,
        correlation_id: str,
        idempotency_key: str,
    ) -> En1BootstrapResult:
        """Deprecated alias: bootstrap with minimal customer payload."""
        return self.bootstrap(
            email=email,
            full_name=display_name,
            organization_name=display_name,
            plan_code="individual",
            phone=phone,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
