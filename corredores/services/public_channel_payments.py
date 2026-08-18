"""Public quote payments — Stripe Checkout when configured; DEV sandbox otherwise.

On trusted PAID: mark quote + CRM WON, then materialize Party + Policy in ESB cartera.
Confirmation only via provider webhook/API or DEV sandbox confirm.
Never trust browser return_url alone.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session

from corredores.domain.crm_constants import STAGE_WON
from corredores.domain.models import (
    CrmOpportunity,
    CrmPipelineStage,
    PublicPaymentAttempt,
    PublicQuote,
    PublicQuoteTraveler,
    PublicSalesChannel,
)
from corredores.domain.public_channel_constants import (
    PAYMENT_FAILED,
    PAYMENT_PENDING,
    PAYMENT_SUCCEEDED,
    QUOTE_CHECKOUT_PENDING,
    QUOTE_PAID,
)
from corredores.services.crm_catalog_seed import ensure_default_crm_catalogs
from corredores.services.public_channel import PublicChannelError, _loads, _money
from corredores.services.public_channel_issuance import (
    PublicIssuanceError,
    issue_party_and_policy_from_paid_quote,
)
from corredores.services.runtime_settings import runtime
from corredores.services.saas_billing import public_base_url, stripe_configured

ATTEMPT_CREATED = "CREATED"
ATTEMPT_REDIRECTED = "REDIRECTED"
ATTEMPT_SUCCEEDED = "SUCCEEDED"
ATTEMPT_FAILED = "FAILED"
ATTEMPT_EXPIRED = "EXPIRED"

PRODUCT_META = "public_channel_quote"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_dev_db() -> bool:
    return "corredores_dev" in (os.environ.get("DATABASE_URL") or "")


def channel_public_base_url() -> str:
    override = (runtime().get("public_channel.base_url") or "").strip()
    if override:
        return override.rstrip("/")
    if _is_dev_db():
        return "https://cotizadorgrupoarsi.etsrv.site"
    return public_base_url()


def _primary_email(session: Session, quote: PublicQuote) -> str | None:
    tr = (
        session.query(PublicQuoteTraveler)
        .filter_by(quote_id=quote.id, is_primary=True)
        .one_or_none()
    )
    if tr and tr.email:
        return tr.email
    tr = (
        session.query(PublicQuoteTraveler)
        .filter_by(quote_id=quote.id)
        .order_by(PublicQuoteTraveler.seq)
        .first()
    )
    return tr.email if tr else None


def _mark_opportunity_won(session: Session, quote: PublicQuote) -> None:
    if not quote.crm_opportunity_id:
        return
    ensure_default_crm_catalogs(session, quote.organization_id)
    opp = session.get(CrmOpportunity, quote.crm_opportunity_id)
    if opp is None or opp.organization_id != quote.organization_id:
        return
    stage = (
        session.query(CrmPipelineStage)
        .filter_by(organization_id=quote.organization_id, code=STAGE_WON, active=True)
        .one_or_none()
    )
    opp.stage_code = STAGE_WON
    if stage:
        opp.stage_id = stage.id
    opp.won_at = opp.won_at or _now()
    if quote.selected_premium is not None:
        opp.estimated_premium = quote.selected_premium
    session.flush()


def apply_successful_payment(
    session: Session,
    attempt: PublicPaymentAttempt,
    *,
    provider_ref: str | None = None,
    raw: dict[str, Any] | None = None,
) -> PublicPaymentAttempt:
    """Idempotent success path — only call after trusted provider confirmation.

    Also materializes Party + Policy in ESB (idempotent repair if already SUCCEEDED).
    """
    quote = session.get(PublicQuote, attempt.quote_id)
    if quote is None:
        raise PublicChannelError("cotización no encontrada")

    if attempt.status != ATTEMPT_SUCCEEDED:
        attempt.status = ATTEMPT_SUCCEEDED
        attempt.confirmed_at = _now()
        if provider_ref:
            attempt.provider_ref = provider_ref
        if raw is not None:
            attempt.raw_event_json = json.dumps(raw, ensure_ascii=False, default=str)[:8000]
        quote.payment_status = PAYMENT_SUCCEEDED
        quote.status = QUOTE_PAID
        quote.paid_at = _now()
        quote.checkout_ref = attempt.provider_ref or quote.checkout_ref
        _mark_opportunity_won(session, quote)
        session.flush()
    elif provider_ref and not attempt.provider_ref:
        attempt.provider_ref = provider_ref

    # Landing sold → ESB cartera (cliente + póliza VIAJE). Safe to re-run.
    try:
        issue_party_and_policy_from_paid_quote(
            session,
            quote,
            actor_id=f"public_channel_payment:{attempt.id}",
        )
    except PublicIssuanceError as e:
        raise PublicChannelError(str(e)) from e
    session.flush()
    return attempt


def start_payment_checkout(
    session: Session,
    quote: PublicQuote,
    channel: PublicSalesChannel,
) -> dict[str, Any]:
    if quote.status not in ("CUSTOMER_DATA", "CHECKOUT_PENDING", "PAID"):
        raise PublicChannelError("complete los datos antes del pago")
    if quote.status == "PAID" and quote.payment_status == PAYMENT_SUCCEEDED:
        return {
            "checkout_ref": quote.checkout_ref,
            "amount": str(quote.selected_premium),
            "currency": quote.currency,
            "provider": "ALREADY_PAID",
            "payment_status": PAYMENT_SUCCEEDED,
            "redirect_url": None,
            "message": "Esta cotización ya está pagada.",
            "already_paid": True,
        }
    if not quote.selected_premium or not quote.selected_plan_snapshot_json:
        raise PublicChannelError("plan no seleccionado")
    snap = _loads(quote.selected_plan_snapshot_json) or {}
    amount = _money(Decimal(str(snap.get("premium", quote.selected_premium))))
    if amount != _money(Decimal(quote.selected_premium)):
        raise PublicChannelError("precio inconsistente — recotice")
    currency = (snap.get("currency") or quote.currency or "USD").upper()
    plan_name = snap.get("name") or quote.selected_plan_code or "Plan"
    idem = f"pq-{quote.id}-{int(amount * 100)}-{currency}"

    existing = (
        session.query(PublicPaymentAttempt)
        .filter_by(idempotency_key=idem)
        .one_or_none()
    )
    if existing and existing.status == ATTEMPT_SUCCEEDED:
        return {
            "checkout_ref": existing.provider_ref or existing.id,
            "amount": str(existing.amount),
            "currency": existing.currency,
            "provider": existing.provider,
            "payment_status": PAYMENT_SUCCEEDED,
            "redirect_url": None,
            "already_paid": True,
            "message": "Pago ya confirmado.",
        }
    if existing and existing.status in (ATTEMPT_CREATED, ATTEMPT_REDIRECTED) and (
        existing.redirect_url or existing.provider == "SANDBOX"
    ):
        quote.status = QUOTE_CHECKOUT_PENDING
        quote.payment_status = PAYMENT_PENDING
        if existing.provider == "SANDBOX":
            existing.redirect_url = None
        session.flush()
        return {
            "checkout_ref": existing.provider_ref or existing.id,
            "amount": str(existing.amount),
            "currency": existing.currency,
            "provider": existing.provider,
            "payment_status": PAYMENT_PENDING,
            "redirect_url": existing.redirect_url,
            "attempt_id": existing.id,
            "message": "Continúa el pago en esta pantalla."
            if existing.provider == "SANDBOX"
            else "Continúa al procesador de pagos.",
            "sandbox": existing.provider == "SANDBOX",
            "in_app": existing.provider == "SANDBOX",
        }

    attempt = existing or PublicPaymentAttempt(
        quote_id=quote.id,
        organization_id=quote.organization_id,
        channel_id=channel.id,
        amount=amount,
        currency=currency,
        status=ATTEMPT_CREATED,
        provider="STRIPE" if stripe_configured() else "SANDBOX",
        idempotency_key=idem,
    )
    if existing is None:
        session.add(attempt)
        session.flush()

    base = channel_public_base_url()
    slug = channel.slug
    token = quote.public_token
    success = f"{base}/public/{slug}/quotes/{token}/result?attempt_id={attempt.id}&session_id={{CHECKOUT_SESSION_ID}}"
    cancel = f"{base}/public/{slug}/quotes/{token}/result?attempt_id={attempt.id}&canceled=1"

    if stripe_configured():
        import stripe

        stripe.api_key = runtime().get("saas.stripe_secret_key")
        email = _primary_email(session, quote)
        unit = int((amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        sess = stripe.checkout.Session.create(
            mode="payment",
            customer_email=email,
            success_url=success,
            cancel_url=cancel,
            line_items=[
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "unit_amount": unit,
                        "product_data": {
                            "name": f"{plan_name} · Seguro de viaje",
                            "description": f"{quote.origin or ''} → {quote.destination or quote.destination_region or ''}".strip(
                                " →"
                            ),
                        },
                    },
                    "quantity": 1,
                }
            ],
            metadata={
                "product": PRODUCT_META,
                "channel_slug": slug,
                "quote_token": token,
                "payment_attempt_id": attempt.id,
                "organization_id": quote.organization_id,
            },
            payment_intent_data={
                "metadata": {
                    "product": PRODUCT_META,
                    "payment_attempt_id": attempt.id,
                }
            },
        )
        attempt.provider = "STRIPE"
        attempt.provider_ref = sess.id
        attempt.redirect_url = sess.url
        attempt.status = ATTEMPT_REDIRECTED
        quote.checkout_ref = sess.id
        quote.payment_status = PAYMENT_PENDING
        quote.status = QUOTE_CHECKOUT_PENDING
        session.flush()
        return {
            "checkout_ref": sess.id,
            "amount": str(amount),
            "currency": currency,
            "provider": "STRIPE",
            "payment_status": PAYMENT_PENDING,
            "redirect_url": sess.url,
            "attempt_id": attempt.id,
            "message": "Serás dirigido a Stripe Checkout.",
        }

    # DEV sandbox — confirm in-wizard (no page jump)
    if not _is_dev_db():
        raise PublicChannelError(
            "Pasarela no configurada. Configure Stripe en Mantenimiento."
        )
    attempt.provider = "SANDBOX"
    attempt.provider_ref = f"SANDBOX-{attempt.id[:8]}"
    attempt.redirect_url = None
    attempt.status = ATTEMPT_REDIRECTED
    quote.checkout_ref = attempt.provider_ref
    quote.payment_status = PAYMENT_PENDING
    quote.status = QUOTE_CHECKOUT_PENDING
    session.flush()
    return {
        "checkout_ref": attempt.provider_ref,
        "amount": str(amount),
        "currency": currency,
        "provider": "SANDBOX",
        "payment_status": PAYMENT_PENDING,
        "redirect_url": None,
        "attempt_id": attempt.id,
        "message": "Confirma el pago en esta misma pantalla.",
        "sandbox": True,
        "in_app": True,
    }


def confirm_sandbox_payment(
    session: Session, *, channel: PublicSalesChannel, quote: PublicQuote, attempt_id: str
) -> PublicPaymentAttempt:
    if not _is_dev_db():
        raise PublicChannelError("sandbox solo disponible en DEV")
    attempt = session.get(PublicPaymentAttempt, attempt_id)
    if attempt is None or attempt.quote_id != quote.id or attempt.channel_id != channel.id:
        raise PublicChannelError("intento de pago no encontrado")
    if attempt.provider != "SANDBOX":
        raise PublicChannelError("este intento no es sandbox")
    return apply_successful_payment(
        session,
        attempt,
        provider_ref=attempt.provider_ref or f"SANDBOX-{secrets.token_hex(4)}",
        raw={"source": "sandbox_confirm", "at": _now().isoformat()},
    )


def confirm_from_stripe_session(session: Session, checkout_session_id: str) -> PublicPaymentAttempt | None:
    import stripe

    if not stripe_configured():
        return None
    stripe.api_key = runtime().get("saas.stripe_secret_key")
    sess = stripe.checkout.Session.retrieve(checkout_session_id)
    meta = sess.metadata or {}
    if meta.get("product") != PRODUCT_META:
        return None
    if sess.payment_status not in {"paid", "no_payment_required"} and sess.status != "complete":
        return None
    attempt_id = meta.get("payment_attempt_id")
    attempt = session.get(PublicPaymentAttempt, attempt_id) if attempt_id else None
    if attempt is None:
        attempt = (
            session.query(PublicPaymentAttempt)
            .filter_by(provider_ref=checkout_session_id)
            .one_or_none()
        )
    if attempt is None:
        return None
    # Amount check against frozen attempt
    paid = Decimal(str((sess.amount_total or 0) / 100))
    if _money(paid) != _money(Decimal(attempt.amount)):
        attempt.status = ATTEMPT_FAILED
        attempt.failure_reason = "amount_mismatch"
        quote = session.get(PublicQuote, attempt.quote_id)
        if quote:
            quote.payment_status = PAYMENT_FAILED
        session.flush()
        raise PublicChannelError("monto no coincide con la cotización")
    return apply_successful_payment(
        session,
        attempt,
        provider_ref=checkout_session_id,
        raw={"stripe_session": checkout_session_id, "payment_status": sess.payment_status},
    )


def sync_attempt_from_return(
    session: Session, *, attempt_id: str | None, session_id: str | None
) -> PublicPaymentAttempt | None:
    """Best-effort sync after browser return — still verifies with Stripe API if possible."""
    if session_id and stripe_configured():
        try:
            return confirm_from_stripe_session(session, session_id)
        except PublicChannelError:
            raise
        except Exception:
            pass
    if attempt_id:
        return session.get(PublicPaymentAttempt, attempt_id)
    return None
