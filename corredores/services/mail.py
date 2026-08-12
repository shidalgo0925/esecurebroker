"""SMTP mail transport — Domain Truth stays in statement_delivery; this only sends bytes.

Config comes from DB (system_settings /mantenimiento), not .env.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from corredores.services.runtime_settings import runtime


@dataclass
class MailResult:
    ok: bool
    detail: str


def mail_configured() -> bool:
    r = runtime()
    return bool(r.bool("mail.enabled") and r.get("mail.smtp_host") and r.get("mail.smtp_from"))


def mail_status() -> dict:
    r = runtime()
    return {
        "mail_enabled": r.bool("mail.enabled"),
        "configured": mail_configured(),
        "smtp_host": r.get("mail.smtp_host"),
        "smtp_port": r.int("mail.smtp_port", 587),
        "smtp_from": r.get("mail.smtp_from"),
        "smtp_tls": r.bool("mail.smtp_tls", True),
        "smtp_ssl": r.bool("mail.smtp_ssl", False),
        "smtp_user_set": bool(r.get("mail.smtp_user")),
        "auto_enabled": r.bool("statements.auto_enabled"),
        "auto_min_days": r.int("statements.min_days_overdue", 1),
        "auto_cooldown_days": r.int("statements.cooldown_days", 7),
        "auto_only_overdue": r.bool("statements.only_overdue", True),
    }


def send_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> MailResult:
    if not mail_configured():
        return MailResult(ok=False, detail="correo deshabilitado o SMTP incompleto (Mantenimiento → Correo)")
    r = runtime()
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return MailResult(ok=False, detail="dirección de correo inválida")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = r.get("mail.smtp_from")
    msg["To"] = to_email
    msg.set_content(text_body or "Ver versión HTML de este mensaje.")
    msg.add_alternative(html_body, subtype="html")

    host = r.get("mail.smtp_host")
    port = r.int("mail.smtp_port", 587)
    user = r.get("mail.smtp_user") or None
    password = r.get("mail.smtp_password") or ""
    use_ssl = r.bool("mail.smtp_ssl", False)
    use_tls = r.bool("mail.smtp_tls", True)

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                if use_tls:
                    context = ssl.create_default_context()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001 — surface to caller as MailResult
        return MailResult(ok=False, detail=f"SMTP error: {exc}")
    return MailResult(ok=True, detail="enviado")
