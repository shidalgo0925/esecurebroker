"""Runtime configuration from DB (system_settings) — editable via /mantenimiento.

Only bootstrap stays in .env: DATABASE_URL, AUTH_* cookie gate.
Operational toggles (mail, statements, OpenAI, Stripe, platform admins) → DB.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from corredores.db import SessionLocal
from corredores.domain.models import SystemSetting

# Catalog = schema of editable settings (metadata in code; values in DB).
SETTING_DEFS: list[dict[str, Any]] = [
    # Correo
    {
        "key": "mail.enabled",
        "category": "correo",
        "label": "Correo habilitado",
        "help_text": "Activa el envío SMTP real.",
        "value_type": "bool",
        "is_secret": False,
        "default": "false",
    },
    {
        "key": "mail.smtp_host",
        "category": "correo",
        "label": "SMTP host",
        "help_text": "Ej. smtp.gmail.com / smtp.sendgrid.net",
        "value_type": "string",
        "is_secret": False,
        "default": "",
    },
    {
        "key": "mail.smtp_port",
        "category": "correo",
        "label": "SMTP puerto",
        "value_type": "int",
        "is_secret": False,
        "default": "587",
    },
    {
        "key": "mail.smtp_user",
        "category": "correo",
        "label": "SMTP usuario",
        "value_type": "string",
        "is_secret": False,
        "default": "",
    },
    {
        "key": "mail.smtp_password",
        "category": "correo",
        "label": "SMTP contraseña",
        "value_type": "secret",
        "is_secret": True,
        "default": "",
    },
    {
        "key": "mail.smtp_from",
        "category": "correo",
        "label": "Remitente (From)",
        "help_text": "Ej. cobranza@esecurebroker.etsrv.site",
        "value_type": "string",
        "is_secret": False,
        "default": "",
    },
    {
        "key": "mail.smtp_tls",
        "category": "correo",
        "label": "SMTP STARTTLS",
        "value_type": "bool",
        "is_secret": False,
        "default": "true",
    },
    {
        "key": "mail.smtp_ssl",
        "category": "correo",
        "label": "SMTP SSL implícito",
        "value_type": "bool",
        "is_secret": False,
        "default": "false",
    },
    # Estados de cuenta
    {
        "key": "statements.auto_enabled",
        "category": "estados",
        "label": "Envío automático de estados",
        "help_text": "Timer diario + botón Ejecutar en Configuración.",
        "value_type": "bool",
        "is_secret": False,
        "default": "false",
    },
    {
        "key": "statements.min_days_overdue",
        "category": "estados",
        "label": "Mín. días de mora",
        "value_type": "int",
        "is_secret": False,
        "default": "1",
    },
    {
        "key": "statements.cooldown_days",
        "category": "estados",
        "label": "Cooldown entre envíos (días)",
        "value_type": "int",
        "is_secret": False,
        "default": "7",
    },
    {
        "key": "statements.only_overdue",
        "category": "estados",
        "label": "Solo clientes con saldo vencido",
        "value_type": "bool",
        "is_secret": False,
        "default": "true",
    },
    # Captura IA
    {
        "key": "capture.openai_api_key",
        "category": "captura",
        "label": "OpenAI API key",
        "help_text": "Para fotos/escaneos. PDF con texto no la requiere.",
        "value_type": "secret",
        "is_secret": True,
        "default": "",
    },
    {
        "key": "capture.openai_vision_model",
        "category": "captura",
        "label": "Modelo Vision",
        "value_type": "string",
        "is_secret": False,
        "default": "gpt-4o-mini",
    },
    # SaaS / Stripe
    {
        "key": "saas.signup_enabled",
        "category": "saas",
        "label": "Registro self-serve habilitado",
        "value_type": "bool",
        "is_secret": False,
        "default": "true",
    },
    {
        "key": "saas.onboarding_url",
        "category": "saas",
        "label": "URL onboarding EN1 (obsoleto)",
        "help_text": (
            "Obsoleto (ADR-006 Ana): CTAs usan /registro en ESB. "
            "No redirigir a UI EN1. Dejar vacío."
        ),
        "value_type": "string",
        "is_secret": False,
        "default": "",
    },
    {
        "key": "saas.en1_commerce_enabled",
        "category": "saas",
        "label": "Comercio EN1 M2M habilitado",
        "help_text": (
            "Si true, checkout/promo/activación van a EN1 DEV vía API (sin simular). "
            "Requiere contrato CODITO + base URL + token M2M. Si false: puente piloto local."
        ),
        "value_type": "bool",
        "is_secret": False,
        "default": "false",
    },
    {
        "key": "saas.en1_api_base_url",
        "category": "saas",
        "label": "EN1 API base URL (M2M)",
        "help_text": "Solo EN1 DEV desde ESB DEV, ej. https://appdev.easynodeone.com",
        "value_type": "string",
        "is_secret": False,
        "default": "",
    },
    {
        "key": "saas.en1_m2m_token",
        "category": "saas",
        "label": "EN1 M2M token",
        "help_text": "Secreto backend; nunca en frontend.",
        "value_type": "secret",
        "is_secret": True,
        "default": "",
    },
    {
        "key": "saas.contact_email",
        "category": "saas",
        "label": "Correo de contacto comercial",
        "value_type": "string",
        "is_secret": False,
        "default": "hola@esecurebroker.etsrv.site",
    },
    {
        "key": "saas.public_base_url",
        "category": "saas",
        "label": "URL pública del producto",
        "value_type": "string",
        "is_secret": False,
        "default": "https://esecurebroker.etsrv.site",
    },
    {
        "key": "saas.stripe_secret_key",
        "category": "saas",
        "label": "Stripe secret key",
        "value_type": "secret",
        "is_secret": True,
        "default": "",
    },
    {
        "key": "saas.stripe_publishable_key",
        "category": "saas",
        "label": "Stripe publishable key",
        "value_type": "string",
        "is_secret": False,
        "default": "",
    },
    {
        "key": "saas.stripe_webhook_secret",
        "category": "saas",
        "label": "Stripe webhook secret",
        "value_type": "secret",
        "is_secret": True,
        "default": "",
    },
    # Plataforma
    {
        "key": "platform.admin_emails",
        "category": "plataforma",
        "label": "Emails dueño plataforma (CSV)",
        "help_text": "Pueden abrir /mantenimiento y todas las orgs.",
        "value_type": "string",
        "is_secret": False,
        "default": "",
    },
    {
        "key": "platform.admin_usernames",
        "category": "plataforma",
        "label": "Usernames dueño plataforma (CSV)",
        "value_type": "string",
        "is_secret": False,
        "default": "",
    },
]

_DEFS_BY_KEY = {d["key"]: d for d in SETTING_DEFS}
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, str] | None = None
_CACHE_AT: float = 0.0
_CACHE_TTL = 15.0


def invalidate_cache() -> None:
    global _CACHE, _CACHE_AT
    with _CACHE_LOCK:
        _CACHE = None
        _CACHE_AT = 0.0


def ensure_settings_table() -> None:
    from corredores.db import engine

    SystemSetting.__table__.create(bind=engine, checkfirst=True)


def ensure_defaults(session: Session, *, actor_id: str | None = "system:seed") -> int:
    """Insert missing keys with catalog defaults. Does not overwrite existing values."""
    created = 0
    for d in SETTING_DEFS:
        row = session.get(SystemSetting, d["key"])
        if row is None:
            session.add(
                SystemSetting(
                    key=d["key"],
                    value=str(d.get("default") or ""),
                    category=d["category"],
                    label=d["label"],
                    help_text=d.get("help_text"),
                    value_type=d["value_type"],
                    is_secret=bool(d["is_secret"]),
                    updated_by=actor_id,
                )
            )
            created += 1
        else:
            # keep value; refresh metadata labels
            row.category = d["category"]
            row.label = d["label"]
            row.help_text = d.get("help_text")
            row.value_type = d["value_type"]
            row.is_secret = bool(d["is_secret"])
    session.flush()
    if created:
        invalidate_cache()
    return created


def clear_en1_ui_onboarding_url(
    session: Session, *, actor_id: str | None = "system:adr006-ux"
) -> int:
    """Clear saas.onboarding_url if it points at EN1 register UI (forbidden for CTAs)."""
    row = session.get(SystemSetting, "saas.onboarding_url")
    if row is None:
        return 0
    val = (row.value or "").strip().lower()
    if not val:
        return 0
    if "easynodeone.com/register" in val or val.endswith("/register"):
        row.value = ""
        row.updated_by = actor_id
        session.flush()
        invalidate_cache()
        return 1
    return 0


def import_legacy_env_once(session: Session, *, actor_id: str | None = "system:migrate-env") -> int:
    """One-shot: copy non-empty .env operational values into empty DB slots."""
    from corredores.config import settings as env

    ensure_defaults(session, actor_id=actor_id)
    mapping = {
        "mail.enabled": "true" if env.mail_enabled else "",
        "mail.smtp_host": env.smtp_host or "",
        "mail.smtp_port": str(env.smtp_port or 587),
        "mail.smtp_user": env.smtp_user or "",
        "mail.smtp_password": env.smtp_password or "",
        "mail.smtp_from": env.smtp_from or "",
        "mail.smtp_tls": "true" if env.smtp_tls else "false",
        "mail.smtp_ssl": "true" if env.smtp_ssl else "false",
        "statements.auto_enabled": "true" if env.statement_auto_enabled else "",
        "statements.min_days_overdue": str(env.statement_auto_min_days_overdue),
        "statements.cooldown_days": str(env.statement_auto_cooldown_days),
        "statements.only_overdue": "true" if env.statement_auto_only_overdue else "false",
        "capture.openai_api_key": env.openai_api_key or "",
        "capture.openai_vision_model": env.openai_vision_model or "gpt-4o-mini",
        "saas.signup_enabled": "true" if env.saas_signup_enabled else "false",
        # No importar URL de UI EN1 (ADR-006 Ana).
        "saas.onboarding_url": "",
        "saas.en1_commerce_enabled": "true" if env.en1_commerce_enabled else "",
        "saas.en1_api_base_url": env.en1_api_base_url or "",
        "saas.en1_m2m_token": env.en1_m2m_token or "",
        "saas.contact_email": env.saas_contact_email or "",
        "saas.public_base_url": env.public_base_url or "",
        "saas.stripe_secret_key": env.stripe_secret_key or "",
        "saas.stripe_publishable_key": env.stripe_publishable_key or "",
        "saas.stripe_webhook_secret": env.stripe_webhook_secret or "",
        "platform.admin_emails": env.platform_admin_emails or "",
        "platform.admin_usernames": env.platform_admin_usernames or "",
    }
    n = 0
    for key, val in mapping.items():
        if not (val or "").strip():
            continue
        row = session.get(SystemSetting, key)
        if row is None:
            continue
        # Only fill empty DB values
        if (row.value or "").strip():
            continue
        # bool enabled flags: only import if true
        if key.endswith(".enabled") or key.endswith("auto_enabled") or key.endswith("signup_enabled"):
            if val.lower() not in {"1", "true", "yes", "on"}:
                continue
        row.value = val
        row.updated_by = actor_id
        n += 1
    session.flush()
    if n:
        invalidate_cache()
    return n


def _load_map(session: Session | None = None) -> dict[str, str]:
    global _CACHE, _CACHE_AT
    now = time.monotonic()
    with _CACHE_LOCK:
        if _CACHE is not None and (now - _CACHE_AT) < _CACHE_TTL:
            return dict(_CACHE)

    owns = session is None
    if owns:
        session = SessionLocal()
    try:
        ensure_settings_table()
        ensure_defaults(session)
        rows = session.query(SystemSetting).all()
        data = {r.key: (r.value if r.value is not None else "") for r in rows}
        # fill catalog defaults for any missing
        for d in SETTING_DEFS:
            data.setdefault(d["key"], str(d.get("default") or ""))
        with _CACHE_LOCK:
            _CACHE = data
            _CACHE_AT = time.monotonic()
        if owns:
            session.commit()
        return dict(data)
    finally:
        if owns:
            session.close()


@dataclass
class RuntimeConfig:
    _data: dict[str, str]

    def get(self, key: str, default: str = "") -> str:
        return (self._data.get(key) if self._data.get(key) is not None else default) or default

    def bool(self, key: str, default: bool = False) -> bool:
        raw = self.get(key, "true" if default else "false").strip().lower()
        if raw in {"1", "true", "yes", "on", "si", "sí"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        return default

    def int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, str(default)).strip() or default)
        except ValueError:
            return default


def runtime(session: Session | None = None) -> RuntimeConfig:
    return RuntimeConfig(_load_map(session))


def set_settings(
    session: Session,
    updates: dict[str, str],
    *,
    actor_id: str | None = None,
) -> list[str]:
    """Apply UI form updates. Empty secret fields keep previous value."""
    ensure_defaults(session, actor_id=actor_id)
    changed: list[str] = []
    for key, raw in updates.items():
        if key not in _DEFS_BY_KEY:
            continue
        d = _DEFS_BY_KEY[key]
        row = session.get(SystemSetting, key)
        if row is None:
            continue
        val = "" if raw is None else str(raw)
        if d["is_secret"] and not val.strip():
            # keep existing secret
            continue
        if d["value_type"] == "bool":
            val = "true" if val.strip().lower() in {"1", "true", "yes", "on", "si", "sí"} else "false"
        if d["value_type"] == "int":
            try:
                val = str(int(val.strip() or "0"))
            except ValueError:
                raise ValueError(f"{d['label']}: debe ser un número entero")
        if row.value != val:
            row.value = val
            row.updated_by = actor_id
            changed.append(key)
    session.flush()
    invalidate_cache()
    return changed


def settings_for_ui(session: Session) -> list[dict[str, Any]]:
    ensure_defaults(session)
    rows = {r.key: r for r in session.query(SystemSetting).all()}
    out: list[dict[str, Any]] = []
    for d in SETTING_DEFS:
        row = rows.get(d["key"])
        value = row.value if row else str(d.get("default") or "")
        display = value
        if d["is_secret"] and value:
            display = "••••••••" if len(value) < 8 else ("••••" + value[-4:])
        out.append(
            {
                **d,
                "value": value,
                "display": display,
                "updated_by": row.updated_by if row else None,
                "updated_at": row.updated_at if row else None,
            }
        )
    return out


def grouped_settings_for_ui(session: Session) -> list[dict[str, Any]]:
    items = settings_for_ui(session)
    order = ["correo", "estados", "captura", "saas", "plataforma"]
    labels = {
        "correo": "Correo (SMTP)",
        "estados": "Estados de cuenta automáticos",
        "captura": "Captura de póliza / IA",
        "saas": "SaaS / Stripe / URLs",
        "plataforma": "Dueños de plataforma",
    }
    groups = []
    for cat in order:
        groups.append(
            {
                "category": cat,
                "title": labels.get(cat, cat),
                "items": [i for i in items if i["category"] == cat],
            }
        )
    return groups
