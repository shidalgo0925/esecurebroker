"""Piloto UI — FastAPI shell over Domain Truth (does not dictate model)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from corredores.web.routes import router

TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Corredores Piloto", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    app.include_router(router)
    return app


app = create_app()
