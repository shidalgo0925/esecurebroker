"""Collaborator invitation email (ADR-008 F7) — uses shared SMTP transport."""

from __future__ import annotations

from html import escape

from corredores.services.mail import MailResult, mail_configured, send_email
from corredores.services.org_access_admin import INVITE_TTL_DAYS


def send_collaborator_invite_email(
    *,
    to_email: str,
    invite_url: str,
    org_name: str,
    invitee_name: str,
    role_label: str,
) -> MailResult:
    """Send invite link. Fail-soft: caller keeps showing the link if not ok."""
    if not mail_configured():
        return MailResult(
            ok=False,
            detail="correo deshabilitado o SMTP incompleto (Configuración / Mantenimiento → Correo)",
        )

    org = escape((org_name or "").strip() or "tu correduría")
    name = escape((invitee_name or "").strip() or "Hola")
    role = escape((role_label or "").strip() or "colaborador")
    url = (invite_url or "").strip()
    if not url.startswith("http"):
        return MailResult(ok=False, detail="enlace de invitación inválido")

    subject = f"Invitación a ESecureBroker — {org_name.strip() or 'correduría'}"
    text = (
        f"{invitee_name or 'Hola'},\n\n"
        f"Te invitaron a {org_name or 'una correduría'} en ESecureBroker "
        f"con el rol {role_label or 'colaborador'}.\n\n"
        f"Acepta aquí (válido {INVITE_TTL_DAYS} días):\n{url}\n\n"
        "Si no esperabas este correo, ignóralo.\n"
    )
    html = f"""<!DOCTYPE html>
<html lang="es"><body style="font-family:system-ui,sans-serif;line-height:1.5;color:#1a1a1a">
  <p>{name},</p>
  <p>Te invitaron a <strong>{org}</strong> en <strong>ESecureBroker</strong>
     con el rol <strong>{role}</strong>.</p>
  <p><a href="{escape(url)}" style="display:inline-block;padding:0.65rem 1.1rem;
     background:#0b3d5c;color:#fff;text-decoration:none;border-radius:6px">
     Aceptar invitación</a></p>
  <p style="font-size:0.9rem;color:#555">El enlace vence en {INVITE_TTL_DAYS} días.
     Si el botón no funciona, copia y pega:<br>
     <span style="word-break:break-all">{escape(url)}</span></p>
  <p style="font-size:0.85rem;color:#777">Si no esperabas este correo, ignóralo.</p>
</body></html>"""

    return send_email(
        to_email=to_email,
        subject=subject,
        html_body=html,
        text_body=text,
    )
