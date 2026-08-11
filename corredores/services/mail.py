"""SMTP mail transport — Domain Truth stays in statement_delivery; this only sends bytes."""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from corredores.config import settings


@dataclass
class MailResult:
    ok: bool
    detail: str


def mail_configured() -> bool:
    return bool(settings.mail_enabled and settings.smtp_host and settings.smtp_from)


def mail_status() -> dict:
    return {
        "mail_enabled": settings.mail_enabled,
        "configured": mail_configured(),
        "smtp_host": settings.smtp_host or "",
        "smtp_port": settings.smtp_port,
        "smtp_from": settings.smtp_from or "",
        "smtp_tls": settings.smtp_tls,
        "smtp_ssl": settings.smtp_ssl,
        "smtp_user_set": bool(settings.smtp_user),
        "auto_enabled": settings.statement_auto_enabled,
        "auto_min_days": settings.statement_auto_min_days_overdue,
        "auto_cooldown_days": settings.statement_auto_cooldown_days,
        "auto_only_overdue": settings.statement_auto_only_overdue,
    }


def send_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> MailResult:
    if not mail_configured():
        return MailResult(ok=False, detail="correo deshabilitado o SMTP incompleto (MAIL_ENABLED / SMTP_*)")
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return MailResult(ok=False, detail="dirección de correo inválida")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.set_content(text_body or "Ver versión HTML de este mensaje.")
    msg.add_alternative(html_body, subtype="html")

    try:
        if settings.smtp_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=30) as smtp:
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                smtp.ehlo()
                if settings.smtp_tls:
                    context = ssl.create_default_context()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
                smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001 — surface to caller as MailResult
        return MailResult(ok=False, detail=f"SMTP error: {exc}")
    return MailResult(ok=True, detail="enviado")
