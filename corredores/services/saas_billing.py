"""Checkout SaaS — Stripe Checkout si hay claves; si no, activación piloto."""

from __future__ import annotations

from sqlalchemy.orm import Session

from corredores.domain.models import OrgSubscription
from corredores.services.runtime_settings import runtime
from corredores.services.saas_plans import SaasPlan, require_plan
from corredores.services.saas_signup import activate_subscription, get_subscription


def stripe_configured() -> bool:
    return bool(runtime().get("saas.stripe_secret_key").strip())


def public_base_url() -> str:
    return (runtime().get("saas.public_base_url") or "http://127.0.0.1:8091").rstrip("/")


def create_stripe_checkout_session(
    *,
    plan: SaasPlan,
    organization_id: str,
    customer_email: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Returns Stripe Checkout Session URL."""
    import stripe

    stripe.api_key = runtime().get("saas.stripe_secret_key")
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=customer_email,
        success_url=success_url,
        cancel_url=cancel_url,
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": int(plan.price_monthly_usd or 0) * 100,
                    "recurring": {"interval": "month"},
                    "product_data": {
                        "name": f"ESecureBroker · {plan.name}",
                        "description": plan.tagline,
                    },
                },
                "quantity": 1,
            }
        ],
        metadata={
            "organization_id": organization_id,
            "plan_code": plan.code,
            "product": "esecurebroker_saas",
        },
        subscription_data={
            "metadata": {
                "organization_id": organization_id,
                "plan_code": plan.code,
            }
        },
    )
    return session.url


def start_checkout(
    db: Session,
    *,
    organization_id: str,
    plan_code: str,
    customer_email: str,
) -> tuple[str, str]:
    """
    Returns (kind, target) where kind is 'redirect' | 'piloto'.
    redirect → Stripe URL; piloto → path to confirm page.
    """
    plan = require_plan(plan_code)
    sub = get_subscription(db, organization_id)
    if sub is None:
        sub = OrgSubscription(
            organization_id=organization_id,
            plan_code=plan.code,
            status="pending",
            billing_provider="piloto",
        )
        db.add(sub)
        db.flush()
    else:
        sub.plan_code = plan.code
        if sub.status not in {"active", "trialing"}:
            sub.status = "pending"
        db.flush()

    if stripe_configured():
        base = public_base_url()
        url = create_stripe_checkout_session(
            plan=plan,
            organization_id=organization_id,
            customer_email=customer_email,
            success_url=f"{base}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/checkout?plan={plan.code}&canceled=1",
        )
        return "redirect", url

    return "piloto", f"/checkout/confirmar?plan={plan.code}"


def confirm_piloto_payment(db: Session, organization_id: str, plan_code: str) -> OrgSubscription:
    plan = require_plan(plan_code)
    sub = get_subscription(db, organization_id)
    if sub is None:
        sub = OrgSubscription(
            organization_id=organization_id,
            plan_code=plan.code,
            status="pending",
            billing_provider="piloto",
        )
        db.add(sub)
        db.flush()
    sub.plan_code = plan.code
    return activate_subscription(db, sub, provider="piloto")


def activate_from_stripe_session(db: Session, checkout_session_id: str) -> OrgSubscription | None:
    import stripe

    stripe.api_key = runtime().get("saas.stripe_secret_key")
    sess = stripe.checkout.Session.retrieve(checkout_session_id)
    org_id = (sess.metadata or {}).get("organization_id")
    plan_code = (sess.metadata or {}).get("plan_code") or "profesional"
    if not org_id:
        return None
    if sess.payment_status not in {"paid", "no_payment_required"} and sess.status != "complete":
        # Still allow complete checkout sessions
        if sess.status != "complete":
            return None
    sub = get_subscription(db, org_id)
    if sub is None:
        sub = OrgSubscription(
            organization_id=org_id,
            plan_code=plan_code,
            status="pending",
            billing_provider="stripe",
        )
        db.add(sub)
        db.flush()
    sub.plan_code = plan_code
    return activate_subscription(
        db,
        sub,
        provider="stripe",
        stripe_customer_id=getattr(sess, "customer", None),
        stripe_subscription_id=getattr(sess, "subscription", None),
        stripe_checkout_session_id=checkout_session_id,
    )
