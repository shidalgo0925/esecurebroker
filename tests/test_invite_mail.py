"""Collaborator invite email (ADR-008 F7 SMTP)."""

from __future__ import annotations

from unittest.mock import patch

from corredores.services.invite_mail import send_collaborator_invite_email
from corredores.services.mail import MailResult


def test_invite_mail_skipped_when_smtp_not_configured():
    with patch("corredores.services.invite_mail.mail_configured", return_value=False):
        r = send_collaborator_invite_email(
            to_email="a@test.local",
            invite_url="https://esecurebroker-dev.etsrv.site/invitacion/tok",
            org_name="Correduría Demo",
            invitee_name="Ana",
            role_label="Administrador",
        )
    assert r.ok is False
    assert "SMTP" in r.detail or "deshabilitado" in r.detail


def test_invite_mail_sends_when_configured():
    with (
        patch("corredores.services.invite_mail.mail_configured", return_value=True),
        patch(
            "corredores.services.invite_mail.send_email",
            return_value=MailResult(ok=True, detail="enviado"),
        ) as send,
    ):
        r = send_collaborator_invite_email(
            to_email="a@test.local",
            invite_url="https://esecurebroker-dev.etsrv.site/invitacion/abc",
            org_name="Correduría Demo",
            invitee_name="Ana",
            role_label="Administrador",
        )
    assert r.ok is True
    kwargs = send.call_args.kwargs
    assert kwargs["to_email"] == "a@test.local"
    assert "invitacion/abc" in kwargs["html_body"]
    assert "Correduría Demo" in kwargs["subject"]
    assert "Aceptar invitación" in kwargs["html_body"]
