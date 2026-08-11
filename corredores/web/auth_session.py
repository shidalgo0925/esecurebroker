"""Piloto session cookie — temporary gate until EN1 auth (ADR-006 / ADR-007).

Do NOT grow this into a user registry. Replace with EN1 tokens/sessions.
Payload v2: actor_id|username|organization_id|exp + HMAC-SHA256(AUTH_SECRET).
Legacy v1 (4 fields without org) still parsed then rejected for tenant routes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from urllib.parse import quote, unquote

from fastapi import Request, Response

from corredores.config import settings

_ACTOR_PREFIX = "piloto:"


@dataclass(frozen=True)
class SessionPrincipal:
    actor_id: str
    username: str
    organization_id: str | None
    exp: int


@dataclass(frozen=True)
class PilotCredential:
    username: str
    password: str
    display_name: str | None = None


def actor_id_for_username(username: str) -> str:
    return f"{_ACTOR_PREFIX}{username.strip()}"


def parse_auth_users() -> list[PilotCredential]:
    """AUTH_USERS=user:pass[:Display Name]|user2:pass2 — or single AUTH_USERNAME/PASSWORD."""
    raw = (settings.auth_users or "").strip()
    out: list[PilotCredential] = []
    if raw:
        for chunk in raw.split("|"):
            chunk = chunk.strip()
            if not chunk:
                continue
            parts = chunk.split(":", 2)
            if len(parts) < 2:
                continue
            user, password = parts[0].strip(), parts[1]
            display = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
            if user and password:
                out.append(PilotCredential(username=user, password=password, display_name=display))
    if not out and (settings.auth_username or "").strip() and (settings.auth_password or "").strip():
        out.append(
            PilotCredential(
                username=settings.auth_username.strip(),
                password=settings.auth_password,
                display_name=settings.auth_display_name or None,
            )
        )
    return out


def auth_ready() -> bool:
    """Ready when secret is set. Env pilots and/or self-serve accounts can authenticate."""
    return bool(settings.auth_enabled and (settings.auth_secret or "").strip())


def verify_credentials(username: str, password: str) -> PilotCredential | None:
    if not auth_ready():
        return None
    needle_u = (username or "").strip()
    needle_p = password or ""
    # 1) Env pilots (AUTH_USERS / AUTH_USERNAME)
    needle_u_b = needle_u.encode("utf-8")
    needle_p_b = needle_p.encode("utf-8")
    for cred in parse_auth_users():
        u_ok = secrets.compare_digest(needle_u_b, cred.username.encode("utf-8"))
        p_ok = secrets.compare_digest(needle_p_b, cred.password.encode("utf-8"))
        if u_ok and p_ok:
            return cred
    # 2) Self-serve BrokerAccount (email login)
    if "@" in needle_u or settings.saas_signup_enabled:
        try:
            from corredores.db import SessionLocal
            from corredores.services.saas_signup import find_account_by_email, verify_password

            with SessionLocal() as session:
                account = find_account_by_email(session, needle_u)
                if account and verify_password(needle_p, account.password_hash):
                    return PilotCredential(
                        username=account.email,
                        password="",  # unused after verify
                        display_name=account.display_name,
                    )
        except Exception:
            return None
    return None


def _sign(payload: str) -> str:
    secret = (settings.auth_secret or "").encode("utf-8")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session_value(username: str, organization_id: str) -> str:
    exp = int(time.time()) + max(1, settings.auth_session_days) * 86400
    actor_id = actor_id_for_username(username)
    org = (organization_id or "").strip()
    payload = f"{actor_id}|{username.strip()}|{org}|{exp}"
    return f"{payload}|{_sign(payload)}"


def parse_session_value(raw: str | None) -> SessionPrincipal | None:
    if not raw or not (settings.auth_secret or "").strip():
        return None
    parts = raw.split("|")
    # v2: actor|user|org|exp|sig
    if len(parts) == 5:
        actor_id, username, org_id, exp_s, sig = parts
        payload = f"{actor_id}|{username}|{org_id}|{exp_s}"
    # legacy v1: actor|user|exp|sig (no org)
    elif len(parts) == 4:
        actor_id, username, exp_s, sig = parts
        org_id = ""
        payload = f"{actor_id}|{username}|{exp_s}"
    else:
        return None
    expected = _sign(payload)
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    if exp < int(time.time()):
        return None
    if not actor_id or not username:
        return None
    return SessionPrincipal(
        actor_id=actor_id,
        username=username,
        organization_id=org_id or None,
        exp=exp,
    )


def read_session(request: Request) -> SessionPrincipal | None:
    raw = request.cookies.get(settings.auth_cookie_name)
    return parse_session_value(raw)


def cookie_secure() -> bool:
    return (settings.app_env or "dev").lower() not in {"dev", "test", "local"}


def attach_session_cookie(response: Response, username: str, organization_id: str) -> None:
    value = create_session_value(username, organization_id)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=value,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=max(1, settings.auth_session_days) * 86400,
        secure=cookie_secure(),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        samesite="lax",
        secure=cookie_secure(),
    )


def safe_next_path(raw: str | None, default: str = "/hoy") -> str:
    if not raw:
        return default
    path = unquote(raw).strip()
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return default
    if path.startswith("/bienvenida") or path.startswith("/login") or path.startswith("/logout"):
        return default
    if path.startswith("/orgs/seleccionar"):
        return default
    if path.startswith("/registro") or path.startswith("/checkout"):
        return default
    return path


def encode_next(path: str) -> str:
    return quote(path, safe="/")


PUBLIC_PATH_EXACT = frozenset(
    {
        "/",
        "/bienvenida",
        "/login",
        "/logout",
        "/orgs/seleccionar",
        "/registro",
        "/planes",
        "/checkout/success",
        "/checkout/cancel",
        "/webhooks/stripe",
    }
)


def is_public_path(path: str) -> bool:
    if path in PUBLIC_PATH_EXACT:
        return True
    if path.startswith("/static/") or path == "/static":
        return True
    if path.startswith("/webhooks/"):
        return True
    if path in {"/favicon.ico", "/docs", "/openapi.json", "/redoc"}:
        return True
    return False
