"""DB-backed runtime settings (mantenimiento)."""

from __future__ import annotations

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.services.runtime_settings import (
    ensure_defaults,
    invalidate_cache,
    runtime,
    set_settings,
)


def setup_module():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    invalidate_cache()


def test_defaults_and_bool_roundtrip():
    with db.SessionLocal() as session:
        n = ensure_defaults(session)
        assert n >= 1
        set_settings(
            session,
            {"mail.enabled": "true", "mail.smtp_host": "smtp.example.com", "mail.smtp_from": "a@b.com"},
            actor_id="test",
        )
        session.commit()
    invalidate_cache()
    r = runtime()
    assert r.bool("mail.enabled") is True
    assert r.get("mail.smtp_host") == "smtp.example.com"


def test_secret_blank_keeps_previous():
    with db.SessionLocal() as session:
        ensure_defaults(session)
        set_settings(session, {"capture.openai_api_key": "sk-test-123456"}, actor_id="test")
        session.commit()
        set_settings(session, {"capture.openai_api_key": ""}, actor_id="test")
        session.commit()
    invalidate_cache()
    assert runtime().get("capture.openai_api_key") == "sk-test-123456"
