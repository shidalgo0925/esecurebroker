"""Registro self-serve + mirror local. SoR comercial = EN1 (API M2M) cuando está habilitado."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from corredores.domain.models import BrokerAccount, Organization, OrgSubscription
from corredores.identity_ids import actor_id_for_username
from corredores.services.saas_plans import require_plan
from corredores.services.tenant import ensure_membership


_PBKDF2_ROUNDS = 120_000


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS
    )
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds_s, salt_hex, digest_hex = stored.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(digest, expected)


def find_account_by_email(session: Session, email: str) -> BrokerAccount | None:
    return (
        session.query(BrokerAccount)
        .filter_by(email=normalize_email(email), active=True)
        .one_or_none()
    )


def find_account_by_subject(session: Session, subject_id: str) -> BrokerAccount | None:
    return (
        session.query(BrokerAccount)
        .filter_by(subject_id=subject_id, active=True)
        .one_or_none()
    )


def get_subscription(session: Session, organization_id: str) -> OrgSubscription | None:
    return (
        session.query(OrgSubscription)
        .filter_by(organization_id=organization_id)
        .one_or_none()
    )


def subscription_allows_access(sub: OrgSubscription | None) -> bool:
    """Sin fila = org legado/piloto env → acceso. Con fila → solo active/trialing."""
    if sub is None:
        return True
    return sub.status in {"active", "trialing"}


def register_broker(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    org_name: str,
    plan_code: str,
    tax_id: str | None = None,
    phone: str | None = None,
) -> tuple[BrokerAccount, Organization, OrgSubscription]:
    email_n = normalize_email(email)
    if not email_n or "@" not in email_n:
        raise ValueError("Correo inválido.")
    if len(password or "") < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
    name = (display_name or "").strip()
    if not name:
        raise ValueError("Indica tu nombre.")
    agency = (org_name or "").strip()
    if not agency:
        raise ValueError("Indica el nombre de tu correduría.")
    if find_account_by_email(session, email_n):
        raise ValueError("Ya existe una cuenta con ese correo. Inicia sesión.")

    plan = require_plan(plan_code)

    from corredores.services.en1_commercial import (
        En1CommercialClient,
        En1CommerceError,
        en1_commerce_enabled,
        new_correlation_id,
    )

    en1_subject: str | None = None
    en1_org_id: str | None = None
    en1_sub_id: str | None = None
    provider = "piloto"

    if en1_commerce_enabled():
        # Fail-closed: no crear cuenta local fingiendo que EN1 respondió.
        client = En1CommercialClient()
        correlation_id = new_correlation_id()
        try:
            ident = client.resolve_or_create_identity(
                email=email_n,
                display_name=name,
                phone=phone,
                correlation_id=correlation_id,
                idempotency_key=f"identity:{email_n}",
            )
            intent = client.create_commercial_intent(
                subject_id=ident.subject_id,
                org_name=agency,
                tax_id=tax_id,
                plan_code=plan.code,
                correlation_id=correlation_id,
                idempotency_key=f"intent:{email_n}:{plan.code}",
            )
        except En1CommerceError as e:
            raise ValueError(e.user_message) from e
        en1_subject = ident.subject_id
        en1_org_id = intent.organization_id
        en1_sub_id = intent.subscription_id
        provider = "en1"

    # Sesión ESB: subject local estable; en1_subject queda en org/sub mirror.
    subject = actor_id_for_username(email_n)
    account = BrokerAccount(
        email=email_n,
        password_hash=hash_password(password),
        display_name=name,
        subject_id=subject,
        active=True,
    )
    org = Organization(
        name=agency[:200],
        active=True,
        external_en1_org_id=en1_org_id,
    )
    session.add(account)
    session.add(org)
    session.flush()
    ensure_membership(
        session,
        subject_id=subject,
        organization_id=org.id,
        display_name=name,
        role_code="OWNER",
    )
    from corredores.services.seed_pilot import seed_pilot

    seed_pilot(session, org_name=org.name)
    sub = OrgSubscription(
        organization_id=org.id,
        plan_code=plan.code,
        status="pending",
        billing_provider=provider,
        # Mirror provisional: EN1 subscription_id hasta columna dedicada
        stripe_subscription_id=en1_sub_id,
        stripe_customer_id=en1_subject,
    )
    session.add(sub)
    session.flush()
    return account, org, sub


def activate_subscription(
    session: Session,
    sub: OrgSubscription,
    *,
    provider: str = "piloto",
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    stripe_checkout_session_id: str | None = None,
) -> OrgSubscription:
    sub.status = "active"
    sub.billing_provider = provider
    sub.activated_at = datetime.now(timezone.utc)
    if stripe_customer_id:
        sub.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id:
        sub.stripe_subscription_id = stripe_subscription_id
    if stripe_checkout_session_id:
        sub.stripe_checkout_session_id = stripe_checkout_session_id
    session.flush()
    return sub
