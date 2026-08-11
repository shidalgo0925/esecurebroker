"""Piloto UI — FastAPI shell over Domain Truth (does not dictate model)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from corredores.config import settings
from corredores.web.auth_session import is_public_path, read_session
from corredores.web.deps import bind_request, reset_request
from corredores.web.routes import router

TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = bind_request(request)
        try:
            return await call_next(request)
        finally:
            reset_request(token)


class PilotoAuthMiddleware(BaseHTTPMiddleware):
    """Env-credential / self-serve gate until EN1 auth lands (ADR-006). Tenant cookie required (ADR-007)."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not settings.auth_enabled or is_public_path(path):
            return await call_next(request)
        principal = read_session(request)
        if principal is None:
            next_q = quote(path, safe="/")
            if request.url.query:
                next_q = quote(f"{path}?{request.url.query}", safe="/?&=")
            return RedirectResponse(f"/?next={next_q}", status_code=303)
        if not principal.organization_id and path != "/orgs/seleccionar":
            return RedirectResponse("/orgs/seleccionar", status_code=303)
        # Suscripción pendiente → solo checkout (orgs sin fila de sub = legado OK)
        if principal.organization_id and not path.startswith("/checkout"):
            try:
                from corredores.db import SessionLocal
                from corredores.services.saas_signup import (
                    get_subscription,
                    subscription_allows_access,
                )

                with SessionLocal() as db:
                    sub = get_subscription(db, principal.organization_id)
                    if not subscription_allows_access(sub):
                        plan = sub.plan_code if sub else "profesional"
                        return RedirectResponse(f"/checkout?plan={plan}", status_code=303)
            except Exception:
                pass
        return await call_next(request)


def ensure_saas_tables() -> None:
    from corredores.db import engine
    from corredores.domain.models import BrokerAccount, OrgSubscription

    BrokerAccount.__table__.create(bind=engine, checkfirst=True)
    OrgSubscription.__table__.create(bind=engine, checkfirst=True)


def create_app() -> FastAPI:
    app = FastAPI(title="ESecureBroker", version="0.1.0")
    try:
        ensure_saas_tables()
    except Exception as e:
        print(f"Warning: ensure_saas_tables: {e}")
    # Last added = outermost. Request context must wrap auth so deps see request.
    app.add_middleware(PilotoAuthMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    app.include_router(router)
    return app


app = create_app()
