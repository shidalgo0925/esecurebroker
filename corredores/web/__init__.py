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
from corredores.web.carrier_incentive_routes import router as carrier_incentive_router
from corredores.web.org_admin_routes import router as org_admin_router
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
        # Org picker (and its logos) must work before a tenant is selected.
        org_logo = (
            path.startswith("/orgs/")
            and path.endswith("/logo")
            and path.count("/") == 3
        )
        if (
            not principal.organization_id
            and path != "/orgs/seleccionar"
            and not org_logo
        ):
            return RedirectResponse("/orgs/seleccionar", status_code=303)
        # Suscripción pendiente → solo checkout (orgs sin fila de sub = legado OK)
        # Dueño de plataforma entra a cualquier org sin bloqueo de billing piloto.
        if principal.organization_id and not path.startswith("/checkout"):
            try:
                from corredores.db import SessionLocal
                from corredores.domain.models import Organization
                from corredores.services.saas_signup import (
                    get_subscription,
                    subscription_allows_access,
                )
                from corredores.services.tenant import is_platform_admin
                from corredores.web.auth_session import clear_session_cookie

                with SessionLocal() as db:
                    if is_platform_admin(
                        db, principal.actor_id, username=principal.username
                    ):
                        return await call_next(request)
                    org = db.get(Organization, principal.organization_id)
                    if org is None or not org.active:
                        # Sesión apunta a org borrada → limpiar y volver al landing.
                        resp = RedirectResponse("/", status_code=303)
                        clear_session_cookie(resp)
                        return resp
                    sub = get_subscription(db, principal.organization_id)
                    if not subscription_allows_access(sub):
                        plan = sub.plan_code if sub else "profesional"
                        return RedirectResponse(f"/checkout?plan={plan}", status_code=303)
            except Exception:
                pass
        return await call_next(request)


def ensure_saas_tables() -> None:
    from corredores.db import engine
    from corredores.domain.models import (
        BrokerAccount,
        MobileRefreshToken,
        OrgInvitation,
        OrgRole,
        OrgRolePermission,
        OrgSubscription,
        SaasPaymentReceipt,
    )

    BrokerAccount.__table__.create(bind=engine, checkfirst=True)
    OrgSubscription.__table__.create(bind=engine, checkfirst=True)
    MobileRefreshToken.__table__.create(bind=engine, checkfirst=True)
    # ADR-008 F7 — prefer alembic; create_all checkfirst as safety net on DEV boots
    OrgRole.__table__.create(bind=engine, checkfirst=True)
    OrgRolePermission.__table__.create(bind=engine, checkfirst=True)
    OrgInvitation.__table__.create(bind=engine, checkfirst=True)
    SaasPaymentReceipt.__table__.create(bind=engine, checkfirst=True)


def ensure_runtime_settings() -> None:
    """Tabla system_settings + defaults + import one-shot desde .env legacy."""
    from corredores.db import SessionLocal
    from corredores.services.runtime_settings import (
        clear_en1_ui_onboarding_url,
        ensure_defaults,
        ensure_settings_table,
        import_legacy_env_once,
    )

    ensure_settings_table()
    with SessionLocal() as session:
        ensure_defaults(session)
        import_legacy_env_once(session)
        clear_en1_ui_onboarding_url(session)
        session.commit()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ESecureBroker",
        version="0.1.0",
        description=(
            "ESecureBroker Web + Mobile API. "
            "ESB GO Mobile contract: `/api/mobile/v1` (OpenAPI tag `mobile-v1`)."
        ),
    )
    try:
        ensure_saas_tables()
    except Exception as e:
        print(f"Warning: ensure_saas_tables: {e}")
    try:
        ensure_runtime_settings()
    except Exception as e:
        print(f"Warning: ensure_runtime_settings: {e}")
    from corredores.web.mobile.errors import MobileAPIError, mobile_api_error_handler
    from corredores.web.mobile.router import router as mobile_router

    app.add_exception_handler(MobileAPIError, mobile_api_error_handler)
    # Last added = outermost. Request context must wrap auth so deps see request.
    app.add_middleware(PilotoAuthMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    app.include_router(router)
    app.include_router(org_admin_router)
    app.include_router(carrier_incentive_router)
    app.include_router(mobile_router)
    return app


app = create_app()
