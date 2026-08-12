"""Access (HMAC signed) + refresh (opaque, hashed) for Mobile API v1."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from corredores.config import settings
from corredores.domain.models import MobileRefreshToken
from corredores.web.mobile.errors import MobileAPIError

ACCESS_TTL_SECONDS = 60 * 60  # 1 hour
REFRESH_TTL_DAYS = 30
_TOKEN_PREFIX = "esbgo"


@dataclass(frozen=True)
class AccessPrincipal:
    subject_id: str
    username: str
    organization_id: str | None
    exp: int
    jti: str


def _secret() -> bytes:
    raw = (settings.auth_secret or "").strip()
    if not raw:
        raise MobileAPIError(
            "auth_misconfigured",
            "AUTH_SECRET is not configured.",
            status_code=503,
        )
    return raw.encode("utf-8")


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_access_token(
    *,
    subject_id: str,
    username: str,
    organization_id: str | None,
    ttl_seconds: int = ACCESS_TTL_SECONDS,
) -> tuple[str, int]:
    exp = int(time.time()) + max(60, ttl_seconds)
    jti = uuid.uuid4().hex
    org = organization_id or "-"
    payload = f"{_TOKEN_PREFIX}|v1|{subject_id}|{username}|{org}|{exp}|{jti}"
    token = f"{payload}|{_sign(payload)}"
    return token, exp


def parse_access_token(token: str) -> AccessPrincipal:
    parts = (token or "").split("|")
    if len(parts) != 8:
        raise MobileAPIError("invalid_token", "Invalid access token.", status_code=401)
    prefix, ver, subject_id, username, org, exp_s, jti, sig = parts
    if prefix != _TOKEN_PREFIX or ver != "v1":
        raise MobileAPIError("invalid_token", "Unsupported token version.", status_code=401)
    payload = "|".join(parts[:7])
    expected = _sign(payload)
    if not hmac.compare_digest(expected, sig):
        raise MobileAPIError("invalid_token", "Invalid access token signature.", status_code=401)
    try:
        exp = int(exp_s)
    except ValueError as e:
        raise MobileAPIError("invalid_token", "Invalid access token expiry.", status_code=401) from e
    if exp < int(time.time()):
        raise MobileAPIError("token_expired", "Access token expired.", status_code=401)
    return AccessPrincipal(
        subject_id=subject_id,
        username=username,
        organization_id=None if org == "-" else org,
        exp=exp,
        jti=jti,
    )


def _hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_refresh_token(
    session: Session,
    *,
    subject_id: str,
    username: str,
    organization_id: str | None,
) -> tuple[str, MobileRefreshToken]:
    raw = secrets.token_urlsafe(48)
    row = MobileRefreshToken(
        subject_id=subject_id,
        username=username,
        organization_id=organization_id,
        token_hash=_hash_refresh(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TTL_DAYS),
    )
    session.add(row)
    session.flush()
    return raw, row


def rotate_refresh_token(
    session: Session,
    raw_refresh: str,
    *,
    organization_id: str | None = None,
) -> tuple[str, MobileRefreshToken, MobileRefreshToken]:
    """Validate refresh, revoke it, issue replacement. Returns (new_raw, old_row, new_row)."""
    th = _hash_refresh(raw_refresh)
    row = (
        session.query(MobileRefreshToken)
        .filter_by(token_hash=th)
        .one_or_none()
    )
    if row is None or row.revoked_at is not None:
        raise MobileAPIError("invalid_refresh", "Refresh token is invalid or revoked.", status_code=401)
    now = datetime.now(timezone.utc)
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        raise MobileAPIError("refresh_expired", "Refresh token expired.", status_code=401)

    org_id = organization_id if organization_id is not None else row.organization_id
    new_raw, new_row = issue_refresh_token(
        session,
        subject_id=row.subject_id,
        username=row.username,
        organization_id=org_id,
    )
    row.revoked_at = now
    row.replaced_by_id = new_row.id
    session.flush()
    return new_raw, row, new_row


def revoke_refresh_token(session: Session, raw_refresh: str) -> None:
    th = _hash_refresh(raw_refresh)
    row = session.query(MobileRefreshToken).filter_by(token_hash=th).one_or_none()
    if row and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        session.flush()
