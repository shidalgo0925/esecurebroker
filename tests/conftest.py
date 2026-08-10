"""Isolate pytest from the app DATABASE_URL (never drop_all on corredores)."""

from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

import corredores.db as db
from corredores.config import settings


def _default_test_url(app_url: str) -> str:
    if app_url.startswith("sqlite"):
        return "sqlite:////opt/corredores/var/corredores_test.db"
    parsed = urlparse(app_url)
    # swap DB name → corredores_test
    path = "/corredores_test"
    return urlunparse(parsed._replace(path=path))


def pytest_configure() -> None:
    test_url = (
        os.environ.get("CORREDORES_TEST_DATABASE_URL")
        or settings.corredores_test_database_url
        or _default_test_url(settings.database_url)
    )
    os.environ["CORREDORES_TEST_DATABASE_URL"] = test_url
    db.configure_engine(test_url)
