"""Piloto shell — sidebar navigation (UX_NAV_SIDEBAR_V1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from corredores.domain.enums import RecommendationDecision
from corredores.domain.models import (
    AuditEvent,
    Carrier,
    CarrierQuoteRequest,
    Claim,
    Document,
    InsuranceLine,
    Party,
    PaymentPlan,
    Policy,
    PolicyTerm,
    QuoteRequest,
    RenewalOpportunity,
    VehicleRisk,
)
from corredores.services.client_360 import build_client_360
from corredores.services.cobranza_board import build_cobranza_board
from corredores.services.documents import (
    DOC_KINDS,
    absolute_path,
    delete_document,
    list_org_documents,
    list_party_documents,
    save_party_pdf,
)
from corredores.services.portfolio_dashboard import build_portfolio_dashboard
from corredores.services.quote_orchestrator import (
    build_comparator,
    create_quote_request,
    dispatch_carriers,
    record_manual_quote,
)
from corredores.services.radar import build_radar
from corredores.services.recommendations import decide_recommendation
from corredores.services.renewals import (
    advance_renewal_status,
    complete_renewal,
    start_multi_carrier_recote,
    start_same_carrier_renewal,
)
from corredores.services.reports import (
    build_report_summary,
    csv_cartera,
    csv_cobranza,
    csv_comisiones,
    csv_cotizaciones,
    csv_pagos,
    csv_renovaciones,
    policy_installment_rows,
    report_preview_rows,
)
from corredores.web.deps import (
    current_actor,
    entitlements,
    get_session,
    resolve_org,
)

router = APIRouter()
from corredores.services.money_format import format_money
from corredores.services.ui_labels import label_es

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["money"] = format_money
templates.env.filters["es"] = label_es

# Sidebar groups — (key, label, href, icon)
NAV_GROUPS = [
    {
        "title": "Operación",
        "links": [
            ("hoy", "Hoy", "/hoy", "sun"),
            ("radar", "Radar", "/radar", "radar"),
        ],
    },
    {
        "title": "Cartera",
        "links": [
            ("cartera", "Panel", "/cartera", "chart"),
            ("clientes", "Clientes", "/clientes", "users"),
            ("polizas", "Pólizas", "/polizas", "folder"),
            ("cobranza", "Cobranza", "/cobranza", "coins"),
            ("morosidad", "Morosidad", "/morosidad", "chart"),
            ("renovaciones", "Renovaciones", "/renovaciones", "refresh"),
            ("reclamos", "Reclamos", "/reclamos", "shield"),
        ],
    },
    {
        "title": "Ventas",
        "links": [
            ("oportunidades", "Oportunidades", "/oportunidades", "target"),
            ("cotizador", "Cotizador", "/cotizador", "scale"),
            ("referidos", "Referidos", "/referidos", "share"),
        ],
    },
    {
        "title": "Gestión",
        "links": [
            ("aseguradoras", "Aseguradoras", "/aseguradoras", "building"),
            ("ramos", "Ramos", "/ramos", "folder"),
            ("productores", "Productores", "/productores", "users"),
            ("comisiones", "Comisiones", "/comisiones", "percent"),
            ("importaciones", "Importaciones", "/importaciones", "file"),
            ("documentos", "Documentos", "/documentos", "file"),
        ],
    },
    {
        "title": "Inteligencia",
        "links": [
            ("oportunidades_ia", "Oportunidades IA", "/oportunidades-ia", "spark"),
        ],
    },
]

NAV_FOOTER = [
    ("reportes", "Reportes", "/reportes", "chart"),
    ("configuracion", "Configuración", "/configuracion", "gear"),
    ("mantenimiento", "Mantenimiento", "/mantenimiento", "gear"),
    ("ayuda", "Ayuda", "/ayuda", "help"),
]

NUEVA_GESTION = [
    ("Captura desde foto", "/captura/poliza-foto", "spark"),
    ("Importar Excel", "/importaciones", "file"),
    ("Nueva póliza", "/polizas/nueva", "folder-plus"),
    ("Nuevo cliente", "/clientes/nuevo", "user-plus"),
    ("Nueva cotización", "/cotizador", "scale"),
    ("Registrar pago", "/cobranza/pagos/nuevo", "coins"),
    ("Nuevo reclamo", "/reclamos/nuevo", "shield"),
]

BAND_LABELS = {
    "BROKEN_PROMISE": "Promesa incumplida",
    "INTERVENTION": "Hay que cobrar",
    "PROMISE": "Promesa activa",
    "EXCEPTION": "Excepción",
    "AUTOMATIC": "Rutinario",
}
BAND_HELP = {
    "BROKEN_PROMISE": "no cumplió — cobra o re-promete hoy",
    "INTERVENTION": "vencido o vence hoy",
    "PROMISE": "esperando la fecha prometida",
    "EXCEPTION": "caso especial",
    "AUTOMATIC": "aún no toca intervenir",
}

POLIZA_STEPS = [
    ("cliente", "Cliente / contratante"),
    ("riesgo", "Riesgo"),
    ("aseguradora", "Aseguradora / producto"),
    ("poliza", "Datos de póliza"),
    ("vigencia", "Vigencia"),
    ("prima", "Prima"),
    ("pagos", "Plan de pagos"),
    ("comision", "Comisión"),
    ("documentos", "Documentos"),
    ("revisar", "Revisar / Guardar"),
]


def _resolve_back(request: Request, active: str, extra: dict) -> tuple[str | None, str]:
    """Botón de retorno global: override explícito o jerarquía por ruta/activo."""
    if "back_href" in extra:
        href = extra.get("back_href")
        if not href:
            return None, ""
        return str(href), str(extra.get("back_label") or "← Volver")

    path = (request.url.path or "/").rstrip("/") or "/"

    # Sub-rutas con padre claro
    if path.startswith("/cartera/") and path != "/cartera":
        return "/cartera", "← Panel"
    if "/beneficios/" in path:
        # /aseguradoras/{id}/beneficios/{plan_id}
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 4 and parts[0] == "aseguradoras" and parts[2] == "beneficios":
            return f"/aseguradoras/{parts[1]}/beneficios", "← Beneficios"
    if path.endswith("/beneficios"):
        return "/aseguradoras", "← Aseguradoras"
    if path.startswith("/polizas/") and path not in {"/polizas/nueva"}:
        return "/polizas", "← Pólizas"
    if path.startswith("/clientes/") and path not in {"/clientes/nuevo"}:
        return "/clientes", "← Clientes"
    if path.startswith("/oportunidades/"):
        return "/oportunidades", "← CRM"
    if path.startswith("/productores/"):
        return "/productores", "← Productores"
    if path.startswith("/importaciones/"):
        return "/importaciones", "← Importaciones"
    if path.startswith("/configuracion/"):
        return "/configuracion", "← Configuración"
    if path.startswith("/cobranza/"):
        return "/cobranza", "← Cobranza"
    if path.startswith("/captura/"):
        return "/hoy", "← Hoy"
    if path.startswith("/reportes/") and "/imprimir" in path:
        return "/reportes?vista=descargas", "← Reportes"
    if path.startswith("/reportes"):
        return "/hoy", "← Hoy"

    by_active = {
        # Incluso Hoy lleva retorno (pedido: todas las pantallas).
        "hoy": ("/cartera", "← Panel"),
        "radar": ("/hoy", "← Hoy"),
        "cartera": ("/hoy", "← Hoy"),
        "clientes": ("/hoy", "← Hoy"),
        "polizas": ("/hoy", "← Hoy"),
        "cobranza": ("/hoy", "← Hoy"),
        "morosidad": ("/cobranza", "← Cobranza"),
        "renovaciones": ("/hoy", "← Hoy"),
        "reclamos": ("/hoy", "← Hoy"),
        "oportunidades": ("/hoy", "← Hoy"),
        "cotizador": ("/hoy", "← Hoy"),
        "referidos": ("/hoy", "← Hoy"),
        "aseguradoras": ("/hoy", "← Hoy"),
        "ramos": ("/aseguradoras", "← Aseguradoras"),
        "productores": ("/hoy", "← Hoy"),
        "comisiones": ("/hoy", "← Hoy"),
        "importaciones": ("/hoy", "← Hoy"),
        "documentos": ("/hoy", "← Hoy"),
        "oportunidades_ia": ("/hoy", "← Hoy"),
        "reportes": ("/hoy", "← Hoy"),
        "configuracion": ("/hoy", "← Hoy"),
        "mantenimiento": ("/hoy", "← Hoy"),
        "ayuda": ("/hoy", "← Hoy"),
    }
    href, label = by_active.get(active, ("/hoy", "← Hoy"))
    return href, label


def _ctx(request: Request, active: str, **extra):
    actor = current_actor(request)
    collapsed = request.cookies.get("sidebar") == "collapsed"
    from corredores.web.auth_session import read_session
    from corredores.services.runtime_settings import runtime

    principal = read_session(request)
    platform_admin = False
    can_switch_org = False
    if principal is not None:
        cfg = runtime()
        emails = {
            p.strip().lower()
            for p in (cfg.get("platform.admin_emails") or "").split(",")
            if p.strip()
        }
        users = {
            p.strip().lower()
            for p in (cfg.get("platform.admin_usernames") or "").split(",")
            if p.strip()
        }
        uname = (principal.username or "").strip().lower()
        tail = (principal.actor_id or "").split(":", 1)[-1].strip().lower()
        platform_admin = uname in users or uname in emails or tail in users or tail in emails
        can_switch_org = True
    footer = list(NAV_FOOTER)
    if not platform_admin:
        footer = [x for x in footer if x[0] != "mantenimiento"]
    from corredores.config import settings as app_settings

    app_env = (app_settings.app_env or "dev").strip().lower()
    back_href, back_label = _resolve_back(request, active, extra)
    base = {
        "request": request,
        "nav_groups": NAV_GROUPS,
        "nav_footer": footer,
        "nueva_gestion": NUEVA_GESTION,
        "active": active,
        "actor_name": actor.display_name,
        "today": date.today().isoformat(),
        "sidebar_collapsed": collapsed,
        # Default collapsed; stays open across pages until user closes it.
        "nueva_gestion_open": request.cookies.get("nueva_gestion") == "open",
        "platform_admin": platform_admin,
        "can_switch_org": can_switch_org,
        "app_env": app_env,
        "is_dev_env": app_env in {"dev", "test", "local"},
        "back_href": back_href,
        "back_label": back_label,
    }
    base.update(extra)
    # Re-aplicar resolución si el caller pasó override en extra (ya contemplado)
    if "back_href" in extra:
        base["back_href"], base["back_label"] = _resolve_back(request, active, extra)
    return base


def _env_flags() -> dict:
    from corredores.config import settings as app_settings

    app_env = (app_settings.app_env or "dev").strip().lower()
    return {
        "app_env": app_env,
        "is_dev_env": app_env in {"dev", "test", "local"},
    }


def _q(value: str | None) -> str:
    return (value or "").strip()


def _match(haystack: str | None, needle: str) -> bool:
    if not needle:
        return True
    return needle.casefold() in (haystack or "").casefold()


def _coming_soon(request: Request, active: str, title: str, blurb: str):
    return templates.TemplateResponse(
        request,
        "coming_soon.html",
        _ctx(request, active, page_title=title, blurb=blurb),
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    from datetime import datetime, timezone

    from corredores.db import SessionLocal
    from corredores.domain.models import Organization
    from corredores.services.runtime_settings import runtime
    from corredores.services.saas_plans import plans_for_landing, start_href
    from corredores.services.saas_signup import get_subscription, subscription_allows_access
    from corredores.web.auth_session import clear_session_cookie, read_session

    principal = read_session(request)
    clear_orphan_cookie = False
    if principal is not None and principal.organization_id:
        # Suscripción pendiente: no empujar a /hoy (el gate de billing
        # rebotaría a checkout y "Cambiar de plan" quedaría atrapado).
        with SessionLocal() as db:
            org = db.get(Organization, principal.organization_id)
            if org is None or not org.active:
                # Cookie huérfana tras borrar cia/usuario en DEV → landing limpia.
                clear_orphan_cookie = True
            else:
                sub = get_subscription(db, principal.organization_id)
                if subscription_allows_access(sub):
                    return RedirectResponse("/hoy", status_code=303)
        # Fall through → landing (precios / re-registro).
    elif principal is not None:
        return RedirectResponse("/orgs/seleccionar", status_code=303)
    cfg = runtime()
    response = templates.TemplateResponse(
        request,
        "landing.html",
        {
            **_env_flags(),
            "plans": plans_for_landing(),
            "year": datetime.now(timezone.utc).year,
            "start_href": start_href("oficina"),
            "login_href": "/login",
            "onboarding_external": bool(cfg.get("saas.onboarding_url").strip()),
            "contact_email": (
                cfg.get("saas.contact_email")
                or cfg.get("mail.smtp_from")
                or "hola@esecurebroker.etsrv.site"
            ),
        },
    )
    if clear_orphan_cookie:
        clear_session_cookie(response)
    return response


@router.get("/bienvenida", response_class=HTMLResponse)
def bienvenida(request: Request, next: str = Query(default="")):
    from corredores.web.auth_session import encode_next, read_session, safe_next_path

    principal = read_session(request)
    if principal is not None and principal.organization_id:
        return RedirectResponse(safe_next_path(next), status_code=303)
    if principal is not None:
        return RedirectResponse("/orgs/seleccionar", status_code=303)
    # Alias histórico → landing pública
    if next:
        return RedirectResponse(f"/?next={encode_next(safe_next_path(next))}", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.get("/planes", response_class=HTMLResponse)
def planes_page(request: Request):
    return RedirectResponse("/#planes", status_code=303)


@router.get("/registro", response_class=HTMLResponse)
def registro_get(request: Request, plan: str = Query(default="oficina")):
    from corredores.config import settings
    from corredores.services.runtime_settings import runtime
    from corredores.services.saas_plans import require_plan
    from corredores.web.auth_session import read_session

    p = require_plan(plan)
    if p.contact_sales:
        return RedirectResponse("/#contacto", status_code=303)
    if read_session(request) is not None:
        return RedirectResponse("/checkout?plan=" + p.code, status_code=303)
    return templates.TemplateResponse(
        request,
        "registro.html",
        {
            **_env_flags(),
            "plan": p,
            "error": None,
            "form": {},
            "signup_enabled": runtime().bool("saas.signup_enabled", True) and bool(settings.auth_secret),
        },
    )


@router.post("/registro")
def registro_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(...),
    org_name: str = Form(...),
    plan: str = Form(default="oficina"),
    session: Session = Depends(get_session),
):
    from corredores.config import settings
    from corredores.services.saas_plans import require_plan
    from corredores.services.saas_signup import register_broker
    from corredores.web.auth_session import attach_session_cookie

    from corredores.services.runtime_settings import runtime

    p = require_plan(plan)
    if not runtime().bool("saas.signup_enabled", True):
        return templates.TemplateResponse(
            request,
            "registro.html",
            {
                **_env_flags(),
                "plan": p,
                "error": "El registro está deshabilitado (Mantenimiento → SaaS).",
                "form": {
                    "email": email,
                    "display_name": display_name,
                    "org_name": org_name,
                },
                "signup_enabled": False,
            },
            status_code=400,
        )
    if not (settings.auth_secret or "").strip():
        return templates.TemplateResponse(
            request,
            "registro.html",
            {
                **_env_flags(),
                "plan": p,
                "error": "Falta AUTH_SECRET en el servidor.",
                "form": {
                    "email": email,
                    "display_name": display_name,
                    "org_name": org_name,
                },
                "signup_enabled": False,
            },
            status_code=400,
        )
    try:
        account, org, _sub = register_broker(
            session,
            email=email,
            password=password,
            display_name=display_name,
            org_name=org_name,
            plan_code=p.code,
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "registro.html",
            {
                **_env_flags(),
                "plan": p,
                "error": str(e),
                "form": {
                    "email": email,
                    "display_name": display_name,
                    "org_name": org_name,
                },
                "signup_enabled": True,
            },
            status_code=400,
        )
    response = RedirectResponse(f"/checkout?plan={p.code}", status_code=303)
    attach_session_cookie(response, account.email, org.id)
    return response


@router.get("/checkout", response_class=HTMLResponse)
def checkout_get(
    request: Request,
    plan: str = Query(default="oficina"),
    canceled: str = Query(default=""),
    session: Session = Depends(get_session),
):
    from corredores.services.en1_commercial import en1_commerce_enabled
    from corredores.services.saas_billing import stripe_configured
    from corredores.services.saas_plans import plans_for_landing, require_plan
    from corredores.services.saas_signup import get_subscription, subscription_allows_access
    from corredores.web.auth_session import read_session

    principal = read_session(request)
    if principal is None or not principal.organization_id:
        return RedirectResponse(f"/registro?plan={require_plan(plan).code}", status_code=303)
    org = resolve_org(session, request)
    sub = get_subscription(session, org.id)
    if subscription_allows_access(sub) and sub is not None and sub.status == "active":
        return RedirectResponse("/hoy", status_code=303)
    p = require_plan(plan or (sub.plan_code if sub else None))
    # Permitir cambio de plan mientras la sub sigue pendiente (EN1 usa plan_code local).
    if sub is not None and sub.status == "pending" and sub.plan_code != p.code and not p.contact_sales:
        sub.plan_code = p.code
        session.add(sub)
        session.commit()

    plan_options = [pl for pl in plans_for_landing() if not pl["contact_sales"]]
    from corredores.services.saas_bank_details import bank_details_for_checkout

    return templates.TemplateResponse(
        request,
        "checkout.html",
        {
            **_env_flags(),
            "plan": p,
            "org_name": org.name,
            "stripe_ready": stripe_configured() and not en1_commerce_enabled(),
            "en1_commerce": en1_commerce_enabled(),
            "canceled": canceled == "1",
            "error": None,
            "promo_code": "",
            "plan_options": plan_options,
            "bank": bank_details_for_checkout(),
            "pay_method": "promo",
            "payment_ref": "",
        },
    )


def _checkout_ctx(
    *,
    plan,
    org_name: str,
    plan_options,
    error: str | None = None,
    promo_code: str = "",
    pay_method: str = "promo",
    payment_ref: str = "",
    canceled: bool = False,
    en1_commerce: bool = True,
    stripe_ready: bool = False,
) -> dict:
    from corredores.services.saas_bank_details import bank_details_for_checkout

    return {
        **_env_flags(),
        "plan": plan,
        "org_name": org_name,
        "stripe_ready": stripe_ready,
        "en1_commerce": en1_commerce,
        "canceled": canceled,
        "error": error,
        "promo_code": promo_code,
        "plan_options": plan_options,
        "bank": bank_details_for_checkout(),
        "pay_method": pay_method,
        "payment_ref": payment_ref,
    }


@router.post("/checkout")
async def checkout_post(
    request: Request,
    plan: str = Form(default="oficina"),
    promo_code: str = Form(default=""),
    pay_method: str = Form(default="promo"),
    payment_ref: str = Form(default=""),
    comprobante: UploadFile | None = File(default=None),
    session: Session = Depends(get_session),
):
    from corredores.services.en1_commercial import en1_commerce_enabled
    from corredores.services.payments import PaymentService
    from corredores.services.saas_billing import confirm_piloto_payment, start_checkout
    from corredores.services.saas_plans import require_plan
    from corredores.services.saas_receipt_verify import create_receipt_report
    from corredores.services.saas_signup import get_subscription
    from corredores.web.auth_session import read_session

    principal = read_session(request)
    if principal is None or not principal.organization_id:
        return RedirectResponse(f"/registro?plan={require_plan(plan).code}", status_code=303)
    org = resolve_org(session, request)
    p = require_plan(plan)
    method = (pay_method or "promo").strip().lower()

    if en1_commerce_enabled():
        import json as json_lib

        from corredores.domain.models import AuditEvent, BrokerAccount
        from corredores.services.saas_plans import plans_for_landing

        sub = get_subscription(session, org.id)
        if sub is None:
            return RedirectResponse(f"/registro?plan={p.code}", status_code=303)
        if sub.status == "pending" and sub.plan_code != p.code and not p.contact_sales:
            sub.plan_code = p.code
            session.add(sub)
            session.commit()
        plan_options = [pl for pl in plans_for_landing() if not pl["contact_sales"]]

        if method in {"transfer", "yappy"}:
            ref = (payment_ref or "").strip()[:120]
            raw = b""
            fname = ""
            ctype = None
            if comprobante is not None and (comprobante.filename or "").strip():
                raw = await comprobante.read()
                fname = comprobante.filename or "comprobante"
                ctype = comprobante.content_type
            if not raw:
                return templates.TemplateResponse(
                    request,
                    "checkout.html",
                    _checkout_ctx(
                        plan=p,
                        org_name=org.name,
                        plan_options=plan_options,
                        error="Debes subir el comprobante de pago. Sin comprobante no puedes continuar.",
                        pay_method=method,
                        payment_ref=ref,
                    ),
                    status_code=400,
                )
            try:
                receipt_row = create_receipt_report(
                    session,
                    organization_id=org.id,
                    subscription_id=sub.id,
                    plan_code=p.code,
                    method=method,
                    payment_reference=ref or None,
                    amount_usd=p.price_monthly_usd,
                    filename=fname,
                    content=raw,
                    content_type=ctype,
                    reported_by=principal.username,
                )
            except ValueError as exc:
                return templates.TemplateResponse(
                    request,
                    "checkout.html",
                    _checkout_ctx(
                        plan=p,
                        org_name=org.name,
                        plan_options=plan_options,
                        error=str(exc),
                        pay_method=method,
                        payment_ref=ref,
                    ),
                    status_code=400,
                )
            session.add(
                AuditEvent(
                    organization_id=org.id,
                    actor_id=principal.username,
                    entity_type="SaasPaymentReceipt",
                    entity_id=receipt_row.id,
                    action="SAAS_PAYMENT_REPORTED",
                    detail_json=json_lib.dumps(
                        {
                            "method": method,
                            "plan_code": p.code,
                            "reference": ref or None,
                            "amount_usd": p.price_monthly_usd,
                            "relative_path": receipt_row.relative_path,
                            "verification_status": "pending",
                            "note": "Sujeto a verificación manual; si no es válido se inhabilita y se contacta al cliente.",
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            session.commit()
            return RedirectResponse("/checkout/pending-payment", status_code=303)

        if method != "promo":
            return templates.TemplateResponse(
                request,
                "checkout.html",
                _checkout_ctx(
                    plan=p,
                    org_name=org.name,
                    plan_options=plan_options,
                    error="Ese método de pago aún no está disponible. Usa promo, transferencia o Yappy.",
                    pay_method="promo",
                ),
                status_code=400,
            )

        if not (promo_code or "").strip():
            return templates.TemplateResponse(
                request,
                "checkout.html",
                _checkout_ctx(
                    plan=p,
                    org_name=org.name,
                    plan_options=plan_options,
                    error="Ingresa un código promocional para completar el pago (DEV).",
                    pay_method="promo",
                ),
                status_code=400,
            )
        acc = (
            session.query(BrokerAccount)
            .filter_by(email=(principal.username or "").strip().lower())
            .one_or_none()
        )
        result = PaymentService().process_promo_activation(
            session,
            organization=org,
            local_subscription=sub,
            promo_code=promo_code,
            actor_email=principal.username,
            actor_name=(acc.display_name if acc else None) or principal.username,
        )
        if not result.ok:
            return templates.TemplateResponse(
                request,
                "checkout.html",
                _checkout_ctx(
                    plan=p,
                    org_name=org.name,
                    plan_options=plan_options,
                    error=result.user_message
                    or "No pudimos completar la activación de tu cuenta.",
                    promo_code=promo_code,
                    pay_method="promo",
                ),
                status_code=400,
            )
        return RedirectResponse("/checkout/success", status_code=303)

    kind, target = start_checkout(
        session,
        organization_id=org.id,
        plan_code=p.code,
        customer_email=principal.username,
    )
    if kind == "redirect":
        return RedirectResponse(target, status_code=303)
    # Puente piloto (solo si comercio EN1 deshabilitado — no es SoR definitivo)
    confirm_piloto_payment(session, org.id, p.code)
    return RedirectResponse("/checkout/success", status_code=303)


@router.get("/checkout/pending-payment", response_class=HTMLResponse)
def checkout_pending_payment(
    request: Request,
    session: Session = Depends(get_session),
):
    from corredores.services.saas_bank_details import bank_details_for_checkout
    from corredores.services.saas_plans import require_plan
    from corredores.services.saas_signup import get_subscription
    from corredores.web.auth_session import read_session

    principal = read_session(request)
    if principal is None or not principal.organization_id:
        return RedirectResponse("/login", status_code=303)
    org = resolve_org(session, request)
    sub = get_subscription(session, org.id)
    p = require_plan(sub.plan_code if sub else "oficina")
    return templates.TemplateResponse(
        request,
        "checkout_pending.html",
        {
            **_env_flags(),
            "org_name": org.name,
            "plan_name": p.name,
            "bank": bank_details_for_checkout(),
        },
    )


@router.get("/checkout/success", response_class=HTMLResponse)
def checkout_success(
    request: Request,
    session_id: str = Query(default=""),
    session: Session = Depends(get_session),
):
    from corredores.services.saas_billing import activate_from_stripe_session, stripe_configured
    from corredores.services.saas_plans import require_plan
    from corredores.services.saas_signup import get_subscription
    from corredores.web.auth_session import read_session

    principal = read_session(request)
    org = None
    plan_name = "Oficina"
    org_name = "tu correduría"
    if session_id and stripe_configured():
        try:
            sub = activate_from_stripe_session(session, session_id)
            if sub is not None:
                plan_name = require_plan(sub.plan_code).name
                from corredores.domain.models import Organization

                o = session.get(Organization, sub.organization_id)
                if o:
                    org = o
                    org_name = o.name
        except Exception:
            pass
    if org is None and principal is not None and principal.organization_id:
        org = resolve_org(session, request)
        org_name = org.name
        sub = get_subscription(session, org.id)
        if sub:
            plan_name = require_plan(sub.plan_code).name
    return templates.TemplateResponse(
        request,
        "checkout_success.html",
        {"plan_name": plan_name, "org_name": org_name},
    )


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, session: Session = Depends(get_session)):
    from corredores.services.runtime_settings import runtime
    from corredores.services.saas_billing import activate_from_stripe_session

    whsec = runtime().get("saas.stripe_webhook_secret").strip()
    if not whsec:
        raise HTTPException(503, "webhook no configurado (Mantenimiento)")
    import stripe

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, whsec)
    except Exception as e:
        raise HTTPException(400, f"webhook inválido: {e}") from e
    if event["type"] == "checkout.session.completed":
        sess_obj = event["data"]["object"]
        sid = sess_obj.get("id")
        if sid:
            activate_from_stripe_session(session, sid)
    return {"ok": True}


@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request, next: str = Query(default=""), error: str = Query(default="")):
    from corredores.config import settings
    from corredores.web.auth_session import auth_ready, encode_next, read_session, safe_next_path

    principal = read_session(request)
    if principal is not None and principal.organization_id:
        return RedirectResponse(safe_next_path(next), status_code=303)
    next_path = safe_next_path(next) if next else "/hoy"
    err = None
    if error == "creds":
        err = "Usuario o contraseña incorrectos."
    elif error == "config":
        err = "Auth incompleta: configura AUTH_PASSWORD / AUTH_USERS y AUTH_SECRET en .env."
    elif error == "disabled":
        err = "Auth deshabilitada (AUTH_ENABLED=false)."
    elif error == "nomembership":
        err = "Tu usuario no tiene organización asignada. Contacta al administrador."
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            **_env_flags(),
            "next": next_path,
            "next_encoded": encode_next(next_path),
            "error": err,
            "auth_ready": auth_ready(),
            "auth_enabled": settings.auth_enabled,
        },
    )


@router.post("/login")
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/hoy"),
    session: Session = Depends(get_session),
):
    from corredores.config import settings
    from corredores.domain.models import Organization
    from corredores.services.tenant import ensure_membership, list_memberships
    from corredores.web.auth_session import (
        actor_id_for_username,
        attach_session_cookie,
        auth_ready,
        encode_next,
        safe_next_path,
        verify_credentials,
    )

    dest = safe_next_path(next)
    if not settings.auth_enabled:
        return RedirectResponse("/login?error=disabled", status_code=303)
    if not auth_ready():
        return RedirectResponse(
            f"/login?error=config&next={encode_next(dest)}", status_code=303
        )
    cred = verify_credentials(username, password)
    if cred is None:
        return RedirectResponse(
            f"/login?error=creds&next={encode_next(dest)}", status_code=303
        )
    subject = actor_id_for_username(cred.username)
    from corredores.services.tenant import is_platform_admin, list_accessible_organizations

    memberships = list_memberships(session, subject)
    admin = is_platform_admin(session, subject, username=cred.username)
    if not memberships and not admin:
        # Piloto convenience: single org → auto-bind (ADR-007 migration path)
        orgs = session.query(Organization).filter_by(active=True).order_by(Organization.created_at).all()
        if len(orgs) == 1:
            ensure_membership(
                session,
                subject_id=subject,
                organization_id=orgs[0].id,
                display_name=cred.display_name or settings.auth_display_name,
            )
            memberships = list_memberships(session, subject)
    accessible = list_accessible_organizations(session, subject, username=cred.username)
    if not accessible:
        return RedirectResponse(
            f"/login?error=nomembership&next={encode_next(dest)}", status_code=303
        )
    if len(accessible) == 1:
        org_id = accessible[0]["organization_id"]
        from corredores.services.saas_signup import get_subscription, subscription_allows_access

        sub = get_subscription(session, org_id)
        if not subscription_allows_access(sub) and not admin:
            response = RedirectResponse(
                f"/checkout?plan={(sub.plan_code if sub else 'oficina')}",
                status_code=303,
            )
            attach_session_cookie(response, cred.username, org_id)
            return response
        response = RedirectResponse(dest, status_code=303)
        attach_session_cookie(response, cred.username, org_id)
        return response
    # Multi-org o dueño de plataforma → elegir (lista ordenada por cartera)
    response = RedirectResponse(
        f"/orgs/seleccionar?next={encode_next(dest)}", status_code=303
    )
    attach_session_cookie(response, cred.username, "")
    return response


@router.get("/orgs/seleccionar", response_class=HTMLResponse)
def orgs_seleccionar(
    request: Request,
    next: str = Query(default="/hoy"),
    session: Session = Depends(get_session),
):
    from corredores.services.tenant import is_platform_admin, list_accessible_organizations
    from corredores.web.auth_session import attach_session_cookie, encode_next, read_session, safe_next_path

    principal = read_session(request)
    if principal is None:
        return RedirectResponse("/login", status_code=303)
    rows = list_accessible_organizations(
        session, principal.actor_id, username=principal.username
    )
    if not rows:
        return RedirectResponse("/login?error=nomembership", status_code=303)
    admin = is_platform_admin(session, principal.actor_id, username=principal.username)
    if len(rows) == 1 and not admin:
        dest = safe_next_path(next)
        response = RedirectResponse(dest, status_code=303)
        attach_session_cookie(response, principal.username, rows[0]["organization_id"])
        return response
    return templates.TemplateResponse(
        request,
        "org_select.html",
        {
            "orgs": rows,
            "next": safe_next_path(next),
            "next_encoded": encode_next(safe_next_path(next)),
            "username": principal.username,
            "platform_admin": admin,
        },
    )


@router.post("/orgs/seleccionar")
def orgs_seleccionar_post(
    request: Request,
    organization_id: str = Form(...),
    next: str = Form(default="/hoy"),
    session: Session = Depends(get_session),
):
    from corredores.services.tenant import assert_membership, ensure_membership, is_platform_admin
    from corredores.web.auth_session import attach_session_cookie, read_session, safe_next_path

    principal = read_session(request)
    if principal is None:
        return RedirectResponse("/login", status_code=303)
    assert_membership(
        session, principal.actor_id, organization_id, username=principal.username
    )
    if is_platform_admin(session, principal.actor_id, username=principal.username):
        ensure_membership(
            session,
            subject_id=principal.actor_id,
            organization_id=organization_id,
            display_name=principal.username,
            role_code="PLATFORM",
        )
    dest = safe_next_path(next)
    response = RedirectResponse(dest, status_code=303)
    attach_session_cookie(response, principal.username, organization_id)
    return response


@router.get("/logout")
@router.post("/logout")
def logout():
    from corredores.web.auth_session import clear_session_cookie

    response = RedirectResponse("/bienvenida", status_code=303)
    clear_session_cookie(response)
    return response


@router.get("/ayuda", response_class=HTMLResponse)
def ayuda(request: Request):
    return templates.TemplateResponse(request, "ayuda.html", _ctx(request, "ayuda"))


@router.get("/hoy", response_class=HTMLResponse)
def hoy(request: Request, session: Session = Depends(get_session)):
    if not entitlements().has("any", "corredores.p0.auto"):
        raise HTTPException(403, "entitlement denied")
    from corredores.services.access_control import scope_allowlists
    from corredores.services.today_home import build_today_home
    from corredores.web.deps import current_access_context

    org = resolve_org(session)
    actor = current_actor(request)
    access = current_access_context(session, request)
    policy_ids = party_ids = None
    if access is not None:
        policy_ids, party_ids = scope_allowlists(session, access)
    home_snap = build_today_home(
        session,
        org.id,
        actor_name=actor.display_name or "Broker",
        policy_ids=policy_ids,
        party_ids=party_ids,
    )
    return templates.TemplateResponse(
        request,
        "hoy.html",
        _ctx(request, "hoy", org_name=org.name, home=home_snap),
    )


@router.get("/radar", response_class=HTMLResponse)
def radar(request: Request, session: Session = Depends(get_session)):
    from corredores.services.access_control import scope_allowlists
    from corredores.web.deps import current_access_context

    org = resolve_org(session)
    access = current_access_context(session, request)
    policy_ids = None
    if access is not None:
        policy_ids, _ = scope_allowlists(session, access)
    snap = build_radar(session, org.id, policy_ids=policy_ids)
    return templates.TemplateResponse(
        request, "radar.html", _ctx(request, "radar", org_name=org.name, snap=snap)
    )


@router.get("/cartera", response_class=HTMLResponse)
def cartera(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session)
    dash = build_portfolio_dashboard(session, org.id)
    return templates.TemplateResponse(
        request,
        "cartera.html",
        _ctx(
            request,
            "cartera",
            org_name=org.name,
            dash=dash,
            charts_json=json.dumps(dash.charts),
            pane="resumen",
        ),
    )


@router.get("/cartera/cobros", response_class=HTMLResponse)
def cartera_cobros(request: Request, session: Session = Depends(get_session)):
    """Dashboard · Cobros — recaudación / aging / vencidos (operativo)."""
    org = resolve_org(session)
    dash = build_portfolio_dashboard(session, org.id)
    return templates.TemplateResponse(
        request,
        "cartera_cobros.html",
        _ctx(request, "cartera", org_name=org.name, dash=dash, pane="cobros"),
    )


@router.get("/cartera/produccion", response_class=HTMLResponse)
def cartera_produccion(request: Request, session: Session = Depends(get_session)):
    """Dashboard · Producción — prima / cia / ramo (≠ incentivos ADR-009)."""
    org = resolve_org(session)
    dash = build_portfolio_dashboard(session, org.id)
    return templates.TemplateResponse(
        request,
        "cartera_produccion.html",
        _ctx(request, "cartera", org_name=org.name, dash=dash, pane="produccion"),
    )


@router.get("/cartera/metas", response_class=HTMLResponse)
def cartera_metas(request: Request, session: Session = Depends(get_session)):
    """Dashboard · Metas — ADR-009 Carrier Incentive Plans (beneficios cia)."""
    from decimal import Decimal

    from corredores.services.carrier_incentives import list_org_plans_with_progress

    org = resolve_org(session)
    rows = list_org_plans_with_progress(session, org.id)
    confirmed = Decimal("0")
    pending = Decimal("0")
    benefit = Decimal("0")
    active_n = 0
    for row in rows:
        plan = row["plan"]
        if plan.status == "ACTIVE":
            active_n += 1
        g = row.get("progress")
        if g is None:
            continue
        confirmed += g.confirmed_amount or Decimal("0")
        pending += g.pending_amount or Decimal("0")
        if g.benefit_stage == "EARNED":
            benefit += g.earned_benefit or Decimal("0")
        else:
            benefit += g.estimated_benefit or Decimal("0")
    summary = {
        "plans_total": len(rows),
        "plans_active": active_n,
        "confirmed_total": confirmed,
        "pending_total": pending,
        "benefit_total": benefit,
    }
    return templates.TemplateResponse(
        request,
        "cartera_metas.html",
        _ctx(
            request,
            "cartera",
            org_name=org.name,
            rows=rows,
            summary=summary,
            pane="metas",
        ),
    )


@router.get("/clientes", response_class=HTMLResponse)
def clientes(
    request: Request,
    q: str = Query(default=""),
    tipo: str = Query(default=""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    needle = _q(q)
    tipo_n = _q(tipo).upper()
    parties = (
        session.query(Party)
        .filter_by(organization_id=org.id)
        .order_by(Party.created_at.desc())
        .limit(500)
        .all()
    )
    policy_counts: dict[str, int] = {}
    for pol in session.query(Policy).filter_by(organization_id=org.id).all():
        policy_counts[pol.client_party_id] = policy_counts.get(pol.client_party_id, 0) + 1
    filtered = []
    for p in parties:
        if tipo_n and (p.party_type or "").upper() != tipo_n:
            continue
        blob = " ".join(
            x
            for x in [
                p.first_name or "",
                p.last_name or "",
                p.legal_name or "",
                p.national_id or "",
                p.phone or "",
                p.email or "",
            ]
            if x
        )
        if not _match(blob, needle):
            continue
        name = " ".join(x for x in [p.first_name or "", p.last_name or ""] if x).strip() or (
            p.legal_name or p.trade_name or "—"
        )
        filtered.append(
            {
                "id": p.id,
                "name": name,
                "national_id": p.national_id or "—",
                "party_type": p.party_type or "—",
                "phone": p.phone or "—",
                "email": p.email or "—",
                "district": p.district or "—",
                "policies": policy_counts.get(p.id, 0),
            }
        )
    return templates.TemplateResponse(
        request,
        "clientes.html",
        _ctx(
            request,
            "clientes",
            org_name=org.name,
            parties=filtered[:100],
            q=needle,
            tipo=tipo_n,
            result_count=len(filtered),
        ),
    )


@router.get("/clientes/nuevo", response_class=HTMLResponse)
def cliente_nuevo(request: Request):
    return templates.TemplateResponse(
        request,
        "cliente_captura.html",
        _ctx(
            request,
            "clientes",
            party=None,
            form_action="/clientes/nuevo",
            cancel_href="/clientes",
            error=None,
        ),
    )


def _save_party_from_form(
    session: Session,
    *,
    org_id: str,
    party: Party | None,
    party_type: str,
    first_name: str,
    last_name: str,
    legal_name: str,
    national_id: str,
    phone: str,
    email: str,
    district: str,
    address: str,
    birth_date: str,
) -> Party:
    from corredores.domain.enums import DataSource, PartyRoleType, PartyType
    from corredores.domain.models import PartyRole

    ptype = PartyType.ORGANIZATION if party_type == "ORGANIZATION" else PartyType.PERSON
    bd = date.fromisoformat(birth_date) if birth_date.strip() else None
    if party is None:
        party = Party(organization_id=org_id, data_source=DataSource.MANUAL)
        session.add(party)
    party.party_type = ptype
    party.first_name = first_name.strip() or None
    party.last_name = last_name.strip() or None
    party.legal_name = legal_name.strip() or None
    party.national_id = national_id.strip() or None
    party.phone = phone.strip() or None
    party.email = email.strip() or None
    party.district = district.strip() or None
    party.address = address.strip() or None
    party.birth_date = bd
    session.flush()
    role = (
        session.query(PartyRole)
        .filter_by(
            organization_id=org_id,
            party_id=party.id,
            role_type=PartyRoleType.CLIENT,
            context_type="GLOBAL",
        )
        .first()
    )
    if role is None:
        session.add(
            PartyRole(
                organization_id=org_id,
                party_id=party.id,
                role_type=PartyRoleType.CLIENT,
                context_type="GLOBAL",
                context_id=None,
            )
        )
    return party


@router.post("/clientes/nuevo")
def cliente_nuevo_post(
    request: Request,
    party_type: str = Form("PERSON"),
    first_name: str = Form(""),
    last_name: str = Form(""),
    legal_name: str = Form(""),
    national_id: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    district: str = Form(""),
    address: str = Form(""),
    birth_date: str = Form(""),
    session: Session = Depends(get_session),
):
    if not first_name.strip() and not legal_name.strip():
        return templates.TemplateResponse(
            request,
            "cliente_captura.html",
            _ctx(
                request,
                "clientes",
                party=None,
                form_action="/clientes/nuevo",
                cancel_href="/clientes",
                error="Nombre o razón social es obligatorio",
            ),
            status_code=400,
        )
    org = resolve_org(session)
    party = _save_party_from_form(
        session,
        org_id=org.id,
        party=None,
        party_type=party_type,
        first_name=first_name,
        last_name=last_name,
        legal_name=legal_name,
        national_id=national_id,
        phone=phone,
        email=email,
        district=district,
        address=address,
        birth_date=birth_date,
    )
    return RedirectResponse(f"/clientes/{party.id}", status_code=303)


@router.get("/clientes/{party_id}/editar", response_class=HTMLResponse)
def cliente_editar(request: Request, party_id: str, session: Session = Depends(get_session)):
    org = resolve_org(session)
    party = session.get(Party, party_id)
    if party is None or party.organization_id != org.id:
        raise HTTPException(404, "cliente no encontrado")
    return templates.TemplateResponse(
        request,
        "cliente_captura.html",
        _ctx(
            request,
            "clientes",
            party=party,
            form_action=f"/clientes/{party_id}/editar",
            cancel_href=f"/clientes/{party_id}",
            error=None,
        ),
    )


@router.post("/clientes/{party_id}/editar")
def cliente_editar_post(
    request: Request,
    party_id: str,
    party_type: str = Form("PERSON"),
    first_name: str = Form(""),
    last_name: str = Form(""),
    legal_name: str = Form(""),
    national_id: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    district: str = Form(""),
    address: str = Form(""),
    birth_date: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    party = session.get(Party, party_id)
    if party is None or party.organization_id != org.id:
        raise HTTPException(404, "cliente no encontrado")
    _save_party_from_form(
        session,
        org_id=org.id,
        party=party,
        party_type=party_type,
        first_name=first_name,
        last_name=last_name,
        legal_name=legal_name,
        national_id=national_id,
        phone=phone,
        email=email,
        district=district,
        address=address,
        birth_date=birth_date,
    )
    return RedirectResponse(f"/clientes/{party_id}", status_code=303)


@router.get("/clientes/{party_id}", response_class=HTMLResponse)
def cliente_360(
    request: Request,
    party_id: str,
    session: Session = Depends(get_session),
    doc_error: str | None = Query(default=None),
):
    org = resolve_org(session)
    try:
        snap = build_client_360(session, org.id, party_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    docs = list_party_documents(session, organization_id=org.id, party_id=party_id)
    return templates.TemplateResponse(
        request,
        "cliente_360.html",
        _ctx(
            request,
            "clientes",
            org_name=org.name,
            snap=snap,
            documents=docs,
            doc_kinds=DOC_KINDS,
            doc_error=doc_error,
        ),
    )


@router.get("/clientes/{party_id}/estado-cuenta", response_class=HTMLResponse)
def cliente_estado_cuenta(
    request: Request, party_id: str, session: Session = Depends(get_session)
):
    from corredores.services.account_cxc import build_account_statement

    org = resolve_org(session)
    party = session.get(Party, party_id)
    try:
        stmt = build_account_statement(session, org.id, party_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return templates.TemplateResponse(
        request,
        "estado_cuenta.html",
        _ctx(
            request,
            "clientes",
            org_name=org.name,
            stmt=stmt,
            party_email=(party.email if party else None) or "",
            flash=request.query_params.get("ok"),
            flash_detail=request.query_params.get("detail"),
        ),
    )


@router.get("/clientes/{party_id}/estado-cuenta/imprimir", response_class=HTMLResponse)
def cliente_estado_cuenta_imprimir(
    party_id: str,
    auto: int = Query(default=0),
    session: Session = Depends(get_session),
):
    from corredores.services.account_cxc import build_account_statement
    from corredores.services.statement_delivery import render_statement_html

    org = resolve_org(session)
    try:
        stmt = build_account_statement(session, org.id, party_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    html = render_statement_html(
        stmt, org_name=org.name, view="estado", auto_print=bool(auto)
    )
    return HTMLResponse(html)


@router.get("/clientes/{party_id}/movimientos/imprimir", response_class=HTMLResponse)
def cliente_movimientos_imprimir(
    party_id: str,
    auto: int = Query(default=0),
    session: Session = Depends(get_session),
):
    from corredores.services.account_cxc import build_account_statement
    from corredores.services.statement_delivery import render_statement_html

    org = resolve_org(session)
    try:
        stmt = build_account_statement(session, org.id, party_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    html = render_statement_html(
        stmt, org_name=org.name, view="movimientos", auto_print=bool(auto)
    )
    return HTMLResponse(html)


@router.post("/clientes/{party_id}/estado-cuenta/enviar")
def cliente_estado_cuenta_enviar(
    party_id: str,
    to_email: str = Form(...),
    session: Session = Depends(get_session),
):
    from corredores.services.statement_delivery import send_account_statement
    from urllib.parse import quote

    org = resolve_org(session)
    actor = current_actor()
    outcome = send_account_statement(
        session,
        org.id,
        party_id,
        to_email=to_email.strip(),
        trigger="MANUAL",
        actor_id=actor.actor_id,
    )
    session.commit()
    if outcome.status == "SENT":
        return RedirectResponse(
            f"/clientes/{party_id}/estado-cuenta?ok=mail_ok", status_code=303
        )
    flag = "mail_skip" if outcome.status == "SKIPPED" else "mail_fail"
    detail = quote(outcome.detail[:180], safe="")
    return RedirectResponse(
        f"/clientes/{party_id}/estado-cuenta?ok={flag}&detail={detail}",
        status_code=303,
    )


@router.get("/clientes/{party_id}/estado-cuenta.csv")
def cliente_estado_cuenta_csv(party_id: str, session: Session = Depends(get_session)):
    from corredores.services.account_cxc import csv_estado_cuenta

    org = resolve_org(session)
    try:
        body = csv_estado_cuenta(session, org.id, party_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="estado_cuenta_{party_id[:8]}.csv"'
        },
    )


@router.post("/clientes/{party_id}/documentos")
async def cliente_documento_upload(
    request: Request,
    party_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    doc_kind: str = Form("OTRO"),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    actor = current_actor(request)
    party = session.get(Party, party_id)
    if party is None or party.organization_id != org.id:
        raise HTTPException(404, "cliente no encontrado")
    content = await file.read()
    try:
        save_party_pdf(
            session,
            organization_id=org.id,
            party_id=party_id,
            filename=file.filename or "documento.pdf",
            content=content,
            content_type=file.content_type,
            title=title.strip() or None,
            doc_kind=doc_kind,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        from urllib.parse import quote

        return RedirectResponse(
            f"/clientes/{party_id}?doc_error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(f"/clientes/{party_id}#documentos", status_code=303)


@router.get("/documentos/{document_id}/archivo")
def documento_descargar(document_id: str, session: Session = Depends(get_session)):
    org = resolve_org(session)
    doc = session.get(Document, document_id)
    if doc is None or doc.organization_id != org.id:
        raise HTTPException(404, "documento no encontrado")
    path = absolute_path(doc)
    if not path.exists():
        raise HTTPException(404, "archivo no encontrado en disco")
    return FileResponse(
        path,
        media_type=doc.content_type or "application/pdf",
        filename=doc.original_filename,
        content_disposition_type="inline",
    )


@router.post("/documentos/{document_id}/eliminar")
def documento_eliminar(
    request: Request,
    document_id: str,
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    actor = current_actor(request)
    doc = session.get(Document, document_id)
    if doc is None or doc.organization_id != org.id:
        raise HTTPException(404, "documento no encontrado")
    party_id = doc.party_id
    try:
        delete_document(
            session, organization_id=org.id, document_id=document_id, actor_id=actor.actor_id
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if party_id:
        return RedirectResponse(f"/clientes/{party_id}#documentos", status_code=303)
    return RedirectResponse("/documentos", status_code=303)


def _capture_stage_dir() -> Path:
    root = Path("/opt/corredores/var/uploads/capture")
    root.mkdir(parents=True, exist_ok=True)
    return root


@router.get("/captura/poliza-foto", response_class=HTMLResponse)
def captura_foto_get(request: Request):
    from corredores.services.runtime_settings import runtime

    return templates.TemplateResponse(
        request,
        "captura_foto.html",
        _ctx(
            request,
            "polizas",
            vision_ready=bool(runtime().get("capture.openai_api_key").strip()),
            error=None,
        ),
    )


@router.post("/captura/poliza-foto", response_class=HTMLResponse)
async def captura_foto_post(
    request: Request,
    file: UploadFile = File(...),
    one_click: str = Form(""),
    session: Session = Depends(get_session),
):
    import uuid

    from corredores.services.policy_photo_capture import extract_policy_photo
    from corredores.services.policy_photo_commit import (
        commit_policy_from_draft,
        draft_ready_for_one_click,
    )
    from corredores.services.runtime_settings import runtime

    org = resolve_org(session)
    actor = current_actor(request)
    vision_ready = bool(runtime().get("capture.openai_api_key").strip())
    content = await file.read()
    if not content:
        return templates.TemplateResponse(
            request,
            "captura_foto.html",
            _ctx(
                request,
                "polizas",
                vision_ready=vision_ready,
                error="Archivo vacío",
            ),
            status_code=400,
        )
    if len(content) > 12 * 1024 * 1024:
        return templates.TemplateResponse(
            request,
            "captura_foto.html",
            _ctx(
                request,
                "polizas",
                vision_ready=vision_ready,
                error="Archivo demasiado grande (máx. 12 MB)",
            ),
            status_code=400,
        )

    filename = file.filename or "poliza.jpg"
    mime = file.content_type or "image/jpeg"
    token = uuid.uuid4().hex
    stage = _capture_stage_dir()
    bin_path = stage / f"{token}.bin"
    meta_path = stage / f"{token}.json"
    bin_path.write_bytes(content)

    draft = extract_policy_photo(content, filename=filename, mime=mime)
    meta_path.write_text(
        json.dumps(
            {
                "filename": filename,
                "mime": mime,
                "draft": draft.as_dict(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Un solo clic: si la IA trae lo mínimo con confianza alta, graba y abre la póliza.
    if one_click == "1":
        ok, missing = draft_ready_for_one_click(draft)
        if ok:
            try:
                policy = commit_policy_from_draft(
                    session,
                    organization_id=org.id,
                    draft=draft,
                    actor_id=actor.actor_id,
                    attach_bytes=content,
                    attach_filename=filename,
                    attach_mime=mime,
                )
                try:
                    bin_path.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return RedirectResponse(f"/polizas/{policy.id}?captura=ok", status_code=303)
            except ValueError as exc:
                draft.warnings.append(str(exc))
        else:
            draft.warnings.append(
                "Un solo clic no pudo cerrar solo — falta: " + ", ".join(missing)
            )

    carriers = session.query(Carrier).filter_by(organization_id=org.id).order_by(Carrier.name).all()
    lines = session.query(InsuranceLine).order_by(InsuranceLine.code).all()
    return templates.TemplateResponse(
        request,
        "captura_foto_revisar.html",
        _ctx(
            request,
            "polizas",
            draft=draft,
            carriers=carriers,
            lines=lines,
            upload_token=token,
            preview_url=None,
            error=None,
        ),
    )


@router.post("/captura/poliza-foto/confirmar")
def captura_foto_confirmar(
    request: Request,
    upload_token: str = Form(...),
    first_name: str = Form(""),
    last_name: str = Form(""),
    national_id: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    district: str = Form(""),
    address: str = Form(""),
    carrier_id: str = Form(""),
    line_id: str = Form(""),
    policy_number: str = Form(""),
    invoice_number: str = Form(""),
    effective_date: str = Form(""),
    expiration_date: str = Form(""),
    annual_premium: str = Form(""),
    num_payments: str = Form("1"),
    payment_form: str = Form(""),
    make: str = Form(""),
    model: str = Form(""),
    year: str = Form(""),
    plate: str = Form(""),
    usage: str = Form(""),
    vehicle_type: str = Form(""),
    color: str = Form(""),
    motor: str = Form(""),
    chassis: str = Form(""),
    attach_file: str = Form(""),
    session: Session = Depends(get_session),
):
    import json as json_lib
    from datetime import date as date_cls

    from corredores.domain.enums import DataSource, DueDateSource, PolicyStatus, TermSource
    from corredores.domain.models import Installment, PaymentPlan, PolicyTerm, VehicleRisk
    from corredores.services.auto_e2e import ensure_auto_line, generate_proposed_installments, suggest_policy_term
    from corredores.services.materialize_portfolio import materialize_portfolio
    from corredores.services.policy_photo_capture import PolicyPhotoDraft, premium_decimal

    org = resolve_org(session)
    actor = current_actor(request)
    stage = _capture_stage_dir()
    bin_path = stage / f"{upload_token}.bin"
    meta_path = stage / f"{upload_token}.json"
    if not bin_path.exists() or not meta_path.exists():
        raise HTTPException(400, "captura expirada — subí la foto de nuevo")

    meta = json_lib.loads(meta_path.read_text(encoding="utf-8"))
    draft = PolicyPhotoDraft(**{k: v for k, v in meta.get("draft", {}).items() if k in PolicyPhotoDraft.__dataclass_fields__})

    if not carrier_id or not policy_number.strip():
        carriers = session.query(Carrier).filter_by(organization_id=org.id).all()
        lines = session.query(InsuranceLine).order_by(InsuranceLine.code).all()
        return templates.TemplateResponse(
            request,
            "captura_foto_revisar.html",
            _ctx(
                request,
                "polizas",
                draft=draft,
                carriers=carriers,
                lines=lines,
                upload_token=upload_token,
                preview_url=None,
                error="Compañía y número de póliza son obligatorios",
            ),
            status_code=400,
        )

    # Upsert party by national_id when possible
    party = None
    nid = national_id.strip() or None
    if nid:
        party = (
            session.query(Party)
            .filter_by(organization_id=org.id, national_id=nid)
            .one_or_none()
        )
    if party is None:
        party = Party(
            organization_id=org.id,
            party_type="PERSON",
            first_name=first_name.strip() or None,
            last_name=last_name.strip() or None,
            national_id=nid,
            phone=phone.strip() or None,
            email=email.strip() or None,
            district=district.strip() or None,
            address=address.strip() or None,
            data_source=DataSource.MANUAL,
        )
        session.add(party)
        session.flush()
    else:
        party.first_name = first_name.strip() or party.first_name
        party.last_name = last_name.strip() or party.last_name
        party.phone = phone.strip() or party.phone
        party.email = email.strip() or party.email
        party.district = district.strip() or party.district
        party.address = address.strip() or party.address

    line = session.get(InsuranceLine, line_id) if line_id else ensure_auto_line(session)
    if line is None:
        line = ensure_auto_line(session)

    eff = date_cls.fromisoformat(effective_date) if effective_date else date_cls.today()
    exp_in = date_cls.fromisoformat(expiration_date) if expiration_date else None
    eff, exp, term_src = suggest_policy_term(
        eff, expiration_date=exp_in, term_source=TermSource.MANUAL if exp_in else TermSource.SYSTEM_GENERATED
    )
    premium = premium_decimal(annual_premium) or Decimal("0")
    n_pay = int(num_payments or "1")

    # Coexistence: skip create if same carrier+line+number
    existing = (
        session.query(Policy)
        .filter_by(
            organization_id=org.id,
            carrier_id=carrier_id,
            insurance_line_id=line.id,
            policy_number=policy_number.strip(),
        )
        .first()
    )
    if existing is not None:
        return RedirectResponse(f"/polizas/{existing.id}", status_code=303)

    notes_bits = []
    if invoice_number.strip():
        notes_bits.append(f"factura:{invoice_number.strip()}")
    if payment_form.strip():
        notes_bits.append(f"forma_pago:{payment_form.strip()}")
    if color.strip():
        notes_bits.append(f"color:{color.strip()}")
    if motor.strip():
        notes_bits.append(f"motor:{motor.strip()}")
    if chassis.strip():
        notes_bits.append(f"chasis:{chassis.strip()}")

    policy = Policy(
        organization_id=org.id,
        carrier_id=carrier_id,
        insurance_line_id=line.id,
        policy_number=policy_number.strip(),
        status=PolicyStatus.ACTIVE,
        client_party_id=party.id,
        annual_premium=premium if premium > 0 else None,
        net_premium=premium if premium > 0 else None,
        data_source=DataSource.MANUAL,
    )
    session.add(policy)
    session.flush()
    session.add(
        PolicyTerm(policy_id=policy.id, effective_date=eff, expiration_date=exp, term_source=term_src)
    )
    if line.code == "AUTO":
        session.add(
            VehicleRisk(
                organization_id=org.id,
                policy_id=policy.id,
                make=make.strip() or None,
                model=model.strip() or None,
                plate=plate.strip() or None,
                year=int(year) if year.strip().isdigit() else None,
                vehicle_type=vehicle_type.strip() or None,
                usage=(usage.strip().upper() or None),
            )
        )
    if premium > 0 and n_pay >= 1:
        plan = PaymentPlan(
            policy_id=policy.id,
            confirmed=True,
            notes="captura foto" + ((" · " + " · ".join(notes_bits)) if notes_bits else ""),
        )
        session.add(plan)
        session.flush()
        for num, due, amt in generate_proposed_installments(
            start_due=eff, count=n_pay, total_amount=premium
        ):
            session.add(
                Installment(
                    payment_plan_id=plan.id,
                    installment_number=num,
                    due_date=due,
                    amount=amt,
                    due_date_source=DueDateSource.SYSTEM_GENERATED,
                )
            )

    if attach_file == "1" and bin_path.exists():
        save_party_pdf(
            session,
            organization_id=org.id,
            party_id=party.id,
            filename=meta.get("filename") or "poliza.pdf",
            content=bin_path.read_bytes(),
            content_type=meta.get("mime"),
            title=f"Póliza {policy_number.strip()}",
            doc_kind="POLIZA",
            policy_id=policy.id,
            actor_id=actor.actor_id,
        )

    materialize_portfolio(session, organization_id=org.id, actor_id=actor.actor_id)

    # cleanup stage
    try:
        bin_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
    except OSError:
        pass

    return RedirectResponse(f"/polizas/{policy.id}", status_code=303)


@router.get("/polizas", response_class=HTMLResponse)
def polizas(
    request: Request,
    q: str = Query(default=""),
    status: str = Query(default=""),
    line: str = Query(default=""),
    carrier: str = Query(default=""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    needle = _q(q)
    status_n = _q(status).upper()
    line_n = _q(line).upper()
    carrier_n = _q(carrier)
    rows = (
        session.query(Policy)
        .filter_by(organization_id=org.id)
        .order_by(Policy.created_at.desc())
        .limit(500)
        .all()
    )
    carriers = session.query(Carrier).filter_by(organization_id=org.id).order_by(Carrier.name).all()
    lines = session.query(InsuranceLine).order_by(InsuranceLine.code).all()
    enriched = []
    for p in rows:
        party = session.get(Party, p.client_party_id)
        car = session.get(Carrier, p.carrier_id)
        ln = session.get(InsuranceLine, p.insurance_line_id)
        term = session.query(PolicyTerm).filter_by(policy_id=p.id).first()
        plan = session.query(PaymentPlan).filter_by(policy_id=p.id).first()
        inst_n = len(plan.installments) if plan else 0
        name = ""
        if party:
            name = " ".join(x for x in [party.first_name or "", party.last_name or ""] if x) or (
                party.legal_name or ""
            )
        line_code = ln.code if ln else "—"
        carrier_name = car.name if car else "—"
        if status_n and (p.status or "").upper() != status_n:
            continue
        if line_n and line_code.upper() != line_n:
            continue
        if carrier_n and carrier_n.casefold() not in carrier_name.casefold():
            continue
        blob = f"{p.policy_number or ''} {name} {carrier_name} {line_code}"
        if not _match(blob, needle):
            continue
        premium = p.annual_premium or p.gross_premium or p.net_premium
        enriched.append(
            {
                "id": p.id,
                "number": p.policy_number,
                "status": p.status,
                "client": name or "—",
                "party_id": p.client_party_id,
                "carrier": carrier_name,
                "line": line_code,
                "premium": premium,
                "effective": term.effective_date if term else None,
                "expiration": term.expiration_date if term else None,
                "installments": inst_n,
                "has_plan": bool(plan),
            }
        )
    # Preferir pólizas con prima/plan para que el registro útil aparezca primero.
    enriched.sort(
        key=lambda r: (
            0 if r["premium"] else 1,
            0 if r["has_plan"] else 1,
            r["number"] or "",
        )
    )
    return templates.TemplateResponse(
        request,
        "polizas.html",
        _ctx(
            request,
            "polizas",
            org_name=org.name,
            policies=enriched[:100],
            q=needle,
            status=status_n,
            line=line_n,
            carrier=carrier_n,
            carriers=carriers,
            lines=lines,
            result_count=len(enriched),
        ),
    )


@router.get("/polizas/nueva", response_class=HTMLResponse)
def poliza_nueva(
    request: Request,
    step: str = Query(default="cliente"),
    quote_request_id: str | None = Query(default=None),
    renewal_id: str | None = Query(default=None),
    party_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    keys = [s[0] for s in POLIZA_STEPS]
    if step not in keys:
        step = "cliente"
    step_i = keys.index(step)
    parties = (
        session.query(Party)
        .filter_by(organization_id=org.id)
        .order_by(Party.created_at.desc())
        .limit(100)
        .all()
    )
    carriers = session.query(Carrier).filter_by(organization_id=org.id).all()
    lines = session.query(InsuranceLine).order_by(InsuranceLine.code).all()
    from_quote = bool(quote_request_id)
    from_renewal = bool(renewal_id)
    preselect_carrier_id = None
    preselect_line_id = None
    prefill_premium = None
    if renewal_id:
        ren = session.get(RenewalOpportunity, renewal_id)
        if ren and ren.organization_id == org.id:
            prev = session.get(Policy, ren.previous_policy_id)
            if prev:
                party_id = party_id or prev.client_party_id
                preselect_carrier_id = prev.carrier_id
                preselect_line_id = prev.insurance_line_id
                prefill_premium = prev.annual_premium or prev.net_premium
    if quote_request_id and not party_id:
        qr = session.get(QuoteRequest, quote_request_id)
        if qr and qr.organization_id == org.id:
            try:
                payload = json.loads(qr.payload_json or "{}")
                party_id = payload.get("party_id") or party_id
            except Exception:
                pass
            preselect_line_id = preselect_line_id or qr.insurance_line_id
    return templates.TemplateResponse(
        request,
        "poliza_nueva.html",
        _ctx(
            request,
            "polizas",
            org_name=org.name,
            steps=POLIZA_STEPS,
            step=step,
            step_i=step_i,
            parties=parties,
            carriers=carriers,
            lines=lines,
            from_quote=from_quote,
            from_renewal=from_renewal,
            quote_request_id=quote_request_id,
            renewal_id=renewal_id,
            preselect_party_id=party_id,
            preselect_carrier_id=preselect_carrier_id,
            preselect_line_id=preselect_line_id,
            prefill_premium=prefill_premium,
        ),
    )


@router.post("/polizas/nueva")
def poliza_nueva_post(
    request: Request,
    party_id: str = Form(""),
    carrier_id: str = Form(""),
    line_id: str = Form(""),
    policy_number: str = Form(""),
    invoice_number: str = Form(""),
    make: str = Form(""),
    model: str = Form(""),
    plate: str = Form(""),
    year: str = Form(""),
    usage: str = Form(""),
    vehicle_type: str = Form(""),
    color: str = Form(""),
    motor: str = Form(""),
    chassis: str = Form(""),
    effective_date: str = Form(""),
    expiration_date: str = Form(""),
    annual_premium: str = Form(""),
    net_premium: str = Form(""),
    gross_premium: str = Form(""),
    payment_form: str = Form(""),
    num_payments: str = Form("12"),
    first_due_date: str = Form(""),
    notes: str = Form(""),
    quote_request_id: str = Form(""),
    renewal_id: str = Form(""),
    session: Session = Depends(get_session),
):
    """Registrar póliza — si quote_request_id/renewal_id vienen, cierra el flujo CRM."""
    from datetime import date as date_cls

    from corredores.domain.enums import DataSource, DueDateSource, PolicyStatus, TermSource
    from corredores.domain.models import Installment, PaymentPlan, PolicyTerm, VehicleRisk
    from corredores.services.auto_e2e import ensure_auto_line, generate_proposed_installments, suggest_policy_term
    from corredores.services.materialize_portfolio import materialize_portfolio

    org = resolve_org(session)
    actor = current_actor(request)
    if not party_id or not carrier_id:
        raise HTTPException(400, "Cliente y aseguradora son obligatorios")
    if not policy_number.strip():
        raise HTTPException(400, "Número de póliza es obligatorio")

    line = session.get(InsuranceLine, line_id) if line_id else ensure_auto_line(session)
    if line is None:
        line = ensure_auto_line(session)

    eff = date_cls.fromisoformat(effective_date) if effective_date else date_cls.today()
    exp_in = date_cls.fromisoformat(expiration_date) if expiration_date else None
    eff, exp, term_src = suggest_policy_term(
        eff, expiration_date=exp_in, term_source=TermSource.MANUAL if exp_in else TermSource.SYSTEM_GENERATED
    )

    def _money(raw: str) -> Decimal | None:
        raw = (raw or "").strip().replace(",", "")
        if not raw:
            return None
        try:
            v = Decimal(raw)
        except Exception:
            return None
        return v if v > 0 else None

    annual = _money(annual_premium)
    net = _money(net_premium)
    gross = _money(gross_premium)
    if annual is None:
        annual = gross or net
    if net is None:
        net = annual
    if gross is None:
        gross = annual
    plan_base = annual or gross or net or Decimal("0")
    n_pay = int(num_payments or "12")
    if (payment_form or "").upper() == "CONTADO":
        n_pay = 1
    first_due = date_cls.fromisoformat(first_due_date) if first_due_date else eff

    notes_bits = []
    if invoice_number.strip():
        notes_bits.append(f"factura:{invoice_number.strip()}")
    if payment_form.strip():
        notes_bits.append(f"forma_pago:{payment_form.strip()}")
    if color.strip():
        notes_bits.append(f"color:{color.strip()}")
    if motor.strip():
        notes_bits.append(f"motor:{motor.strip()}")
    if chassis.strip():
        notes_bits.append(f"chasis:{chassis.strip()}")
    if notes.strip():
        notes_bits.append(notes.strip())

    policy = Policy(
        organization_id=org.id,
        carrier_id=carrier_id,
        insurance_line_id=line.id,
        policy_number=policy_number.strip() or None,
        status=PolicyStatus.ACTIVE,
        client_party_id=party_id,
        annual_premium=annual,
        net_premium=net,
        gross_premium=gross,
        data_source=DataSource.MANUAL,
    )
    session.add(policy)
    session.flush()
    session.add(
        PolicyTerm(
            policy_id=policy.id,
            effective_date=eff,
            expiration_date=exp,
            term_source=term_src,
        )
    )
    if line.code == "AUTO":
        session.add(
            VehicleRisk(
                organization_id=org.id,
                policy_id=policy.id,
                make=make.strip() or None,
                model=model.strip() or None,
                plate=plate.strip() or None,
                year=int(year) if year.strip().isdigit() else None,
                vehicle_type=vehicle_type.strip() or None,
                usage=(usage.strip().upper() or None),
            )
        )
    if plan_base > 0 and n_pay >= 1:
        plan = PaymentPlan(
            policy_id=policy.id,
            confirmed=True,
            notes=" · ".join(notes_bits) if notes_bits else "alta manual",
        )
        session.add(plan)
        session.flush()
        for num, due, amt in generate_proposed_installments(
            start_due=first_due, count=n_pay, total_amount=plan_base
        ):
            session.add(
                Installment(
                    payment_plan_id=plan.id,
                    installment_number=num,
                    due_date=due,
                    amount=amt,
                    due_date_source=DueDateSource.SYSTEM_GENERATED,
                )
            )
    elif notes_bits:
        session.add(
            PaymentPlan(
                policy_id=policy.id,
                confirmed=False,
                notes=" · ".join(notes_bits),
            )
        )
    if renewal_id:
        ren = session.get(RenewalOpportunity, renewal_id)
        if ren and ren.organization_id == org.id:
            complete_renewal(session, ren, new_policy_id=policy.id, actor_id=actor.actor_id)
    if quote_request_id:
        session.add(
            AuditEvent(
                organization_id=org.id,
                actor_id=actor.actor_id,
                entity_type="QuoteRequest",
                entity_id=quote_request_id,
                action="EMITTED_POLICY",
                detail_json=json.dumps({"policy_id": policy.id}),
            )
        )
    session.flush()
    materialize_portfolio(session, organization_id=org.id, actor_id=actor.actor_id)
    return RedirectResponse(f"/polizas/{policy.id}", status_code=303)


@router.get("/polizas/{policy_id}/plan-pagos", response_class=HTMLResponse)
def poliza_plan_pagos_get(
    request: Request,
    policy_id: str,
    session: Session = Depends(get_session),
    error: str = Query(default=""),
    ok: str = Query(default=""),
):
    from corredores.services.payment_plan_edit import build_plan_edit_view

    org = resolve_org(session)
    try:
        view = build_plan_edit_view(session, org.id, policy_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    first_due = (
        view.effective_date.isoformat()
        if view.effective_date
        else date.today().isoformat()
    )
    if view.installments:
        first_due = view.installments[0]["due_date"]
    return templates.TemplateResponse(
        request,
        "plan_pagos_editar.html",
        _ctx(
            request,
            "polizas",
            org_name=org.name,
            view=view,
            regen_count=max(1, len(view.installments) or 3),
            first_due=first_due,
            error=error or None,
            ok=ok or None,
        ),
    )


@router.post("/polizas/{policy_id}/plan-pagos/regenerar")
def poliza_plan_pagos_regenerar(
    request: Request,
    policy_id: str,
    count: int = Form(...),
    first_due: str = Form(...),
    frequency_months: int = Form(1),
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.payment_plan_edit import regenerate_payment_plan

    org = resolve_org(session)
    actor = current_actor(request)
    try:
        regenerate_payment_plan(
            session,
            organization_id=org.id,
            policy_id=policy_id,
            count=int(count),
            first_due=date.fromisoformat(first_due),
            frequency_months=int(frequency_months or 1),
            actor_id=actor.actor_id,
        )
    except (ValueError, TypeError) as exc:
        return RedirectResponse(
            f"/polizas/{policy_id}/plan-pagos?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/polizas/{policy_id}/plan-pagos?ok={quote('Plan regenerado')}",
        status_code=303,
    )


@router.post("/polizas/{policy_id}/plan-pagos")
async def poliza_plan_pagos_post(
    request: Request,
    policy_id: str,
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.payment_plan_edit import update_open_installments

    org = resolve_org(session)
    actor = current_actor(request)
    form = await request.form()
    ids = form.getlist("inst_id")
    updates = []
    for iid in ids:
        due = form.get(f"due_{iid}")
        amt = form.get(f"amt_{iid}")
        updates.append({"id": iid, "due_date": due, "amount": amt})
    try:
        update_open_installments(
            session,
            organization_id=org.id,
            policy_id=policy_id,
            updates=updates,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        return RedirectResponse(
            f"/polizas/{policy_id}/plan-pagos?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/polizas/{policy_id}/plan-pagos?ok={quote('Cuotas actualizadas')}",
        status_code=303,
    )


@router.get("/polizas/{policy_id}", response_class=HTMLResponse)
def poliza_detalle(request: Request, policy_id: str, session: Session = Depends(get_session)):
    from corredores.domain.models import Commission, CommissionSplit, RenewalOpportunity

    org = resolve_org(session)
    policy = session.get(Policy, policy_id)
    if policy is None or policy.organization_id != org.id:
        raise HTTPException(404, "póliza no encontrada")
    party = session.get(Party, policy.client_party_id)
    carrier = session.get(Carrier, policy.carrier_id)
    line = session.get(InsuranceLine, policy.insurance_line_id)
    term = session.query(PolicyTerm).filter_by(policy_id=policy.id).first()
    vehicle = session.query(VehicleRisk).filter_by(policy_id=policy.id).first()
    plan = session.query(PaymentPlan).filter_by(policy_id=policy.id).first()
    installments = policy_installment_rows(session, policy.id)
    open_balance = sum((i["balance"] for i in installments), Decimal("0"))
    client_name = ""
    client_id_doc = ""
    if party:
        client_name = " ".join(x for x in [party.first_name or "", party.last_name or ""] if x) or (
            party.legal_name or party.trade_name or ""
        )
        client_id_doc = party.national_id or ""
    commission = session.query(Commission).filter_by(policy_id=policy.id).first()
    split = None
    if commission:
        split = session.query(CommissionSplit).filter_by(commission_id=commission.id).first()
    renewal = (
        session.query(RenewalOpportunity)
        .filter_by(organization_id=org.id, previous_policy_id=policy.id)
        .order_by(RenewalOpportunity.target_date.asc())
        .first()
    )
    premium_annual = policy.annual_premium
    premium_net = policy.net_premium
    premium_gross = policy.gross_premium
    premium_show = premium_annual or premium_gross or premium_net
    return templates.TemplateResponse(
        request,
        "poliza_detalle.html",
        _ctx(
            request,
            "polizas",
            org_name=org.name,
            policy=policy,
            term=term,
            vehicle=vehicle,
            plan=plan,
            client_name=client_name or "—",
            client_id_doc=client_id_doc,
            carrier_name=carrier.name if carrier else "—",
            carrier_code=carrier.code if carrier else "—",
            line_code=line.code if line else "—",
            line_name=line.name if line else "—",
            installments=installments,
            open_balance=open_balance,
            premium_show=premium_show,
            premium_annual=premium_annual,
            premium_net=premium_net,
            premium_gross=premium_gross,
            commission=commission,
            split=split,
            renewal=renewal,
        ),
    )


@router.get("/cobranza", response_class=HTMLResponse)
def cobranza(
    request: Request,
    q: str = Query(default=""),
    banda: str = Query(default=""),
    estado: str = Query(default=""),
    vencimiento: str = Query(default=""),
    aging: str = Query(default=""),
    party_id: str = Query(default=""),
    session: Session = Depends(get_session),
):
    from corredores.services.account_cxc import aging_key_for_days
    from corredores.services.promises import refresh_overdue_promises

    org = resolve_org(session)
    actor = current_actor(request)
    refresh_overdue_promises(session, org.id, actor_id=actor.actor_id)
    board = build_cobranza_board(session, org.id)
    order = ["BROKEN_PROMISE", "INTERVENTION", "PROMISE", "EXCEPTION", "AUTOMATIC"]
    needle = _q(q)
    banda_n = _q(banda).upper()
    estado_n = _q(estado).upper()
    venc_n = _q(vencimiento).lower()
    aging_n = _q(aging).lower().replace("–", "-")
    party_n = _q(party_id)
    today = date.today()

    filtered_bands: dict[str, list] = {k: [] for k in order}
    filtered_totals: dict[str, Decimal] = {k: Decimal("0") for k in order}
    for key in order:
        for r in board.bands.get(key, []):
            if banda_n and key != banda_n:
                continue
            if party_n and r.party_id != party_n:
                continue
            if estado_n and (r.status or "").upper() != estado_n:
                continue
            if venc_n == "hoy" and r.due_date != today:
                continue
            if venc_n == "vencido" and r.due_date >= today:
                continue
            if venc_n == "por_vencer" and r.due_date < today:
                continue
            if aging_n:
                days = getattr(r, "days_overdue", 0) or 0
                if aging_key_for_days(days) != aging_n:
                    continue
            blob = f"{r.party_name} {r.policy_number or ''} {r.installment_number}"
            if not _match(blob, needle):
                continue
            filtered_bands[key].append(r)
            filtered_totals[key] += r.balance

    board.bands = filtered_bands
    board.totals = filtered_totals
    action_total = (
        filtered_totals.get("BROKEN_PROMISE", Decimal("0"))
        + filtered_totals.get("INTERVENTION", Decimal("0"))
        + filtered_totals.get("PROMISE", Decimal("0"))
    )
    return templates.TemplateResponse(
        request,
        "cobranza.html",
        _ctx(
            request,
            "cobranza",
            org_name=org.name,
            board=board,
            band_order=order,
            band_labels=BAND_LABELS,
            band_help=BAND_HELP,
            q=needle,
            banda=banda_n,
            estado=estado_n,
            vencimiento=venc_n,
            aging=aging_n,
            party_id=party_n,
            result_count=sum(len(v) for v in filtered_bands.values()),
            broken_n=len(filtered_bands.get("BROKEN_PROMISE", [])),
            intervention_n=len(filtered_bands.get("INTERVENTION", [])),
            promise_n=len(filtered_bands.get("PROMISE", [])),
            action_total=action_total,
            flash=request.query_params.get("ok"),
        ),
    )


@router.get("/morosidad", response_class=HTMLResponse)
def morosidad(
    request: Request,
    q: str = Query(default=""),
    aging: str = Query(default=""),
    session: Session = Depends(get_session),
):
    from corredores.services.account_cxc import build_morosity_analysis

    org = resolve_org(session)
    needle = _q(q)
    aging_n = _q(aging).replace("–", "-")
    analysis = build_morosity_analysis(session, org.id, aging=aging_n or None)
    rows = analysis.rows
    if needle:
        rows = [
            r
            for r in rows
            if _match(f"{r['party_name']} {r['policy_number'] or ''}", needle)
        ]
    return templates.TemplateResponse(
        request,
        "morosidad.html",
        _ctx(
            request,
            "morosidad",
            org_name=org.name,
            analysis=analysis,
            rows=rows,
            q=needle,
            aging=aging_n,
        ),
    )


@router.get("/morosidad/imprimir", response_class=HTMLResponse)
def morosidad_imprimir(
    q: str = Query(default=""),
    aging: str = Query(default=""),
    auto: int = Query(default=0),
    session: Session = Depends(get_session),
):
    from corredores.services.account_cxc import build_morosity_analysis
    from corredores.services.statement_delivery import render_morosity_html

    org = resolve_org(session)
    needle = _q(q)
    aging_n = _q(aging).replace("–", "-")
    analysis = build_morosity_analysis(session, org.id, aging=aging_n or None)
    rows = analysis.rows
    if needle:
        rows = [
            r
            for r in rows
            if _match(f"{r['party_name']} {r['policy_number'] or ''}", needle)
        ]
    html = render_morosity_html(
        analysis,
        org_name=org.name,
        rows=rows,
        aging=aging_n,
        auto_print=bool(auto),
    )
    return HTMLResponse(html)


def _open_installment_options(session: Session, organization_id: str, *, policy_id: str | None = None):
    board = build_cobranza_board(session, organization_id)
    opts = []
    for rows in board.bands.values():
        for r in rows:
            if policy_id and r.policy_id != policy_id:
                continue
            opts.append(r)
    opts.sort(key=lambda r: (r.due_date, r.installment_number))
    return opts


@router.get("/cobranza/pagos/nuevo", response_class=HTMLResponse)
def pago_nuevo(
    request: Request,
    installment_id: str | None = Query(default=None),
    policy_id: str | None = Query(default=None),
    modo: str = Query(default="cobrar"),
    session: Session = Depends(get_session),
):
    from datetime import timedelta

    org = resolve_org(session)
    options = _open_installment_options(session, org.id, policy_id=policy_id)
    prefill = None
    if installment_id:
        prefill = next((o for o in options if o.installment_id == installment_id), None)
    elif options and policy_id:
        prefill = options[0]
    promise_default = (date.today() + timedelta(days=3)).isoformat()
    return templates.TemplateResponse(
        request,
        "pago_nuevo.html",
        _ctx(
            request,
            "cobranza",
            org_name=org.name,
            options=options,
            prefill=prefill,
            error=None,
            modo="promesa" if modo.lower() == "promesa" else "cobrar",
            promise_default=promise_default,
        ),
    )


@router.post("/cobranza/pagos/nuevo")
def pago_nuevo_post(
    request: Request,
    installment_id: str = Form(...),
    amount: str = Form(...),
    payment_date: str = Form(...),
    method: str = Form("TRANSFER"),
    reference: str = Form(""),
    session: Session = Depends(get_session),
):
    from datetime import timedelta

    from corredores.domain.models import Installment
    from corredores.services.payments import record_payment
    from corredores.services.promises import fulfill_promises_for_installment

    org = resolve_org(session)
    actor = current_actor(request)
    options = _open_installment_options(session, org.id)
    inst = session.get(Installment, installment_id)
    if inst is None:
        raise HTTPException(404, "cuota no encontrada")
    plan = session.get(PaymentPlan, inst.payment_plan_id)
    policy = session.get(Policy, plan.policy_id) if plan else None
    if policy is None or policy.organization_id != org.id:
        raise HTTPException(404, "póliza no encontrada")
    try:
        record_payment(
            session,
            organization_id=org.id,
            policy_id=policy.id,
            amount=Decimal(amount),
            payment_date=date.fromisoformat(payment_date),
            installment_id=installment_id,
            actor_id=actor.actor_id,
            method=method.strip() or None,
            reference=reference.strip() or None,
        )
        fulfill_promises_for_installment(
            session,
            organization_id=org.id,
            installment_id=installment_id,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        prefill = next((o for o in options if o.installment_id == installment_id), None)
        return templates.TemplateResponse(
            request,
            "pago_nuevo.html",
            _ctx(
                request,
                "cobranza",
                org_name=org.name,
                options=options,
                prefill=prefill,
                error=str(exc),
                modo="cobrar",
                promise_default=(date.today() + timedelta(days=3)).isoformat(),
            ),
            status_code=400,
        )
    return RedirectResponse("/cobranza?ok=pago", status_code=303)


@router.post("/cobranza/promesas/nueva")
def promesa_nueva_post(
    request: Request,
    installment_id: str = Form(...),
    promised_amount: str = Form(...),
    promised_date: str = Form(...),
    comment: str = Form(""),
    session: Session = Depends(get_session),
):
    from corredores.domain.models import Installment
    from corredores.domain.enums import PaymentPromiseStatus
    from corredores.domain.models import PaymentPromise
    from corredores.services.promises import create_promise

    org = resolve_org(session)
    actor = current_actor(request)
    inst = session.get(Installment, installment_id)
    if inst is None:
        raise HTTPException(404, "cuota no encontrada")
    plan = session.get(PaymentPlan, inst.payment_plan_id)
    policy = session.get(Policy, plan.policy_id) if plan else None
    if policy is None or policy.organization_id != org.id:
        raise HTTPException(404, "póliza no encontrada")
    # Cierra promesas abiertas previas de la misma cuota antes de re-prometer.
    old = (
        session.query(PaymentPromise)
        .filter_by(organization_id=org.id, installment_id=inst.id)
        .filter(
            PaymentPromise.status.in_(
                [PaymentPromiseStatus.ACTIVE, PaymentPromiseStatus.BROKEN]
            )
        )
        .all()
    )
    for p in old:
        p.status = PaymentPromiseStatus.CANCELLED
        session.add(
            AuditEvent(
                organization_id=org.id,
                actor_id=actor.actor_id,
                entity_type="PaymentPromise",
                entity_id=p.id,
                action="CANCELLED",
                detail_json=json.dumps({"reason": "replaced_by_new_promise"}),
            )
        )
    create_promise(
        session,
        organization_id=org.id,
        policy_id=policy.id,
        installment_id=inst.id,
        party_id=policy.client_party_id,
        promised_amount=Decimal(promised_amount),
        promised_date=date.fromisoformat(promised_date),
        comment=comment.strip() or None,
        actor_id=actor.actor_id,
    )
    return RedirectResponse("/cobranza?ok=promesa&banda=PROMISE", status_code=303)


@router.get("/cotizador", response_class=HTMLResponse)
def cotizador(
    request: Request,
    quote_request_id: str | None = Query(default=None),
    q: str = Query(default=""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    needle = _q(q)
    raw_quotes = (
        session.query(QuoteRequest)
        .filter_by(organization_id=org.id)
        .order_by(QuoteRequest.created_at.desc())
        .limit(100)
        .all()
    )
    quotes = []
    for qr in raw_quotes:
        line = session.get(InsuranceLine, qr.insurance_line_id)
        payload = {}
        try:
            payload = json.loads(qr.payload_json or "{}")
        except Exception:
            payload = {}
        label = payload.get("note") or payload.get("client_name") or "—"
        if payload.get("party_id"):
            party = session.get(Party, payload["party_id"])
            if party:
                label = " ".join(
                    x for x in [party.first_name or "", party.last_name or ""] if x
                ) or (party.legal_name or label)
        cqrs = session.query(CarrierQuoteRequest).filter_by(quote_request_id=qr.id).all()
        answered = sum(1 for c in cqrs if c.status not in ("PENDING", "FAILED", "TIMEOUT"))
        blob = f"{qr.id} {line.code if line else ''} {label}"
        if needle and not _match(blob, needle):
            continue
        quotes.append(
            {
                "id": qr.id,
                "line_code": line.code if line else "—",
                "label": label,
                "created_at": qr.created_at,
                "carriers": len(cqrs),
                "responses": answered,
            }
        )
    comparator = None
    preselect_party_id = None
    if quote_request_id:
        qr = session.get(QuoteRequest, quote_request_id)
        if qr and qr.organization_id == org.id:
            try:
                comparator = build_comparator(session, quote_request_id)
            except Exception:
                comparator = []
            try:
                payload = json.loads(qr.payload_json or "{}")
                preselect_party_id = payload.get("party_id")
            except Exception:
                preselect_party_id = None
        else:
            quote_request_id = None
    parties_raw = (
        session.query(Party)
        .filter_by(organization_id=org.id)
        .order_by(Party.created_at.desc())
        .limit(200)
        .all()
    )
    parties = []
    for p in parties_raw:
        name = " ".join(x for x in [p.first_name or "", p.last_name or ""] if x).strip() or (
            p.legal_name or p.trade_name or "—"
        )
        parties.append({"id": p.id, "name": name, "national_id": p.national_id})
    carriers = session.query(Carrier).filter_by(organization_id=org.id, active=True).order_by(Carrier.name).all()
    lines = session.query(InsuranceLine).order_by(InsuranceLine.code).all()
    return templates.TemplateResponse(
        request,
        "cotizador.html",
        _ctx(
            request,
            "cotizador",
            org_name=org.name,
            quotes=quotes[:40],
            comparator=comparator or [],
            selected_id=quote_request_id,
            q=needle,
            parties=parties,
            carriers=carriers,
            lines=lines,
            preselect_party_id=preselect_party_id,
            form_error=request.query_params.get("error"),
        ),
    )


@router.post("/cotizador/nuevo")
def cotizador_nuevo_post(
    request: Request,
    party_id: str = Form(""),
    line_id: str = Form(""),
    note: str = Form(""),
    carrier_ids: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    actor = current_actor(request)
    if not party_id or not line_id:
        return RedirectResponse("/cotizador?error=Cliente+y+ramo+obligatorios", status_code=303)
    if isinstance(carrier_ids, str):
        carrier_ids = [carrier_ids]
    carrier_ids = [c for c in carrier_ids if c]
    if not carrier_ids:
        return RedirectResponse("/cotizador?error=Selecciona+al+menos+una+aseguradora", status_code=303)
    party = session.get(Party, party_id)
    if party is None or party.organization_id != org.id:
        return RedirectResponse("/cotizador?error=Cliente+no+encontrado", status_code=303)
    client_name = ""
    if getattr(party, "party_type", None) == "ORGANIZATION":
        client_name = party.legal_name or party.trade_name or ""
    else:
        client_name = " ".join(x for x in [party.first_name or "", party.last_name or ""] if x) or (
            party.legal_name or ""
        )
    qr = create_quote_request(
        session,
        organization_id=org.id,
        insurance_line_id=line_id,
        payload={
            "party_id": party_id,
            "client_name": client_name,
            "note": note.strip(),
        },
        actor_id=actor.actor_id,
    )
    dispatch_carriers(session, qr, carrier_ids, actor_id=actor.actor_id)
    return RedirectResponse(f"/cotizador?quote_request_id={qr.id}", status_code=303)


@router.post("/cotizador/{quote_request_id}/manual")
def cotizador_manual_post(
    request: Request,
    quote_request_id: str,
    carrier_quote_request_id: str = Form(""),
    premium: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    actor = current_actor(request)
    qr = session.get(QuoteRequest, quote_request_id)
    if qr is None or qr.organization_id != org.id:
        raise HTTPException(404, "cotización no encontrada")
    cqr = session.get(CarrierQuoteRequest, carrier_quote_request_id)
    if cqr is None or cqr.quote_request_id != qr.id:
        raise HTTPException(400, "respuesta de compañía inválida")
    try:
        amount = Decimal(premium or "0")
    except Exception:
        return RedirectResponse(
            f"/cotizador?quote_request_id={quote_request_id}&error=Prima+inválida",
            status_code=303,
        )
    if amount <= 0:
        return RedirectResponse(
            f"/cotizador?quote_request_id={quote_request_id}&error=Prima+debe+ser+mayor+a+0",
            status_code=303,
        )
    record_manual_quote(
        session,
        cqr,
        organization_id=org.id,
        premium=amount,
        actor_id=actor.actor_id,
    )
    return RedirectResponse(f"/cotizador?quote_request_id={quote_request_id}", status_code=303)


@router.get("/renovaciones", response_class=HTMLResponse)
def renovaciones(
    request: Request,
    q: str = Query(default=""),
    status: str = Query(default=""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    needle = _q(q)
    status_n = _q(status).upper()
    raw = (
        session.query(RenewalOpportunity)
        .filter_by(organization_id=org.id)
        .order_by(RenewalOpportunity.target_date)
        .limit(500)
        .all()
    )
    rows = []
    for r in raw:
        if status_n and (r.status or "").upper() != status_n:
            continue
        pol = session.get(Policy, r.previous_policy_id)
        party = session.get(Party, pol.client_party_id) if pol else None
        client = ""
        if party:
            client = " ".join(x for x in [party.first_name or "", party.last_name or ""] if x) or (
                party.legal_name or ""
            )
        number = pol.policy_number if pol else ""
        blob = f"{r.status} {number} {client} {r.target_date or ''}"
        if not _match(blob, needle):
            continue
        rows.append(
            {
                "id": r.id,
                "status": r.status,
                "target_date": r.target_date,
                "previous_policy_id": r.previous_policy_id,
                "new_policy_id": r.new_policy_id,
                "policy_number": number or (r.previous_policy_id[:8] if r.previous_policy_id else "—"),
                "client": client or "—",
                "party_id": pol.client_party_id if pol else None,
            }
        )
    statuses = sorted({r.status for r in raw if r.status})
    return templates.TemplateResponse(
        request,
        "renovaciones.html",
        _ctx(
            request,
            "renovaciones",
            org_name=org.name,
            rows=rows[:100],
            q=needle,
            status=status_n,
            statuses=statuses,
            result_count=len(rows),
        ),
    )


@router.get("/reclamos", response_class=HTMLResponse)
def reclamos(
    request: Request,
    q: str = Query(default=""),
    status: str = Query(default=""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    needle = _q(q)
    status_n = _q(status).upper()
    raw = (
        session.query(Claim)
        .filter_by(organization_id=org.id)
        .order_by(Claim.created_at.desc())
        .limit(500)
        .all()
    )
    rows = []
    for r in raw:
        if status_n and (r.status or "").upper() != status_n:
            continue
        blob = f"{r.claim_number or ''} {r.status} {r.policy_id} {r.source or ''}"
        if not _match(blob, needle):
            continue
        rows.append(r)
    statuses = sorted({c.status for c in raw if c.status})
    return templates.TemplateResponse(
        request,
        "reclamos.html",
        _ctx(
            request,
            "reclamos",
            org_name=org.name,
            rows=rows[:100],
            q=needle,
            status=status_n,
            statuses=statuses,
            result_count=len(rows),
        ),
    )


@router.get("/reclamos/nuevo", response_class=HTMLResponse)
def reclamo_nuevo(request: Request):
    return _coming_soon(
        request,
        "reclamos",
        "Nuevo reclamo",
        "Alta de reclamo desde la bandeja — el dominio Claim ya existe; el formulario completo llega con el diseño de expediente.",
    )


@router.get("/oportunidades", response_class=HTMLResponse)
def oportunidades(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session)
    renewals = (
        session.query(RenewalOpportunity)
        .filter_by(organization_id=org.id)
        .filter(
            RenewalOpportunity.status.in_(
                [
                    "UPCOMING",
                    "CONTACT_PENDING",
                    "CONTACTED",
                    "QUOTING",
                    "PROPOSAL_SENT",
                    "WAITING_CLIENT",
                    "ACCEPTED",
                ]
            )
        )
        .order_by(RenewalOpportunity.target_date.asc())
        .limit(100)
        .all()
    )
    opportunities = []
    premium_at_stake = Decimal("0")
    pipeline = {"upcoming": 0, "quoting": 0, "waiting": 0}
    for ren in renewals:
        pol = session.get(Policy, ren.previous_policy_id)
        party = session.get(Party, pol.client_party_id) if pol else None
        name = ""
        if party:
            name = " ".join(x for x in [party.first_name or "", party.last_name or ""] if x) or (
                party.legal_name or ""
            )
        prem = (pol.annual_premium or pol.net_premium or Decimal("0")) if pol else Decimal("0")
        premium_at_stake += prem
        if ren.status in ("UPCOMING", "CONTACT_PENDING"):
            pipeline["upcoming"] += 1
        elif ren.status == "QUOTING":
            pipeline["quoting"] += 1
        elif ren.status in ("PROPOSAL_SENT", "WAITING_CLIENT"):
            pipeline["waiting"] += 1
        opportunities.append(
            {
                "id": ren.id,
                "kind": "RENOVACIÓN",
                "policy_id": pol.id if pol else ren.previous_policy_id,
                "policy_number": pol.policy_number if pol else "—",
                "client": name or "—",
                "status": ren.status,
                "target_date": ren.target_date,
                "premium": prem if prem else None,
            }
        )
    return templates.TemplateResponse(
        request,
        "oportunidades.html",
        _ctx(
            request,
            "oportunidades",
            org_name=org.name,
            opportunities=opportunities,
            premium_at_stake=premium_at_stake,
            pipeline=pipeline,
        ),
    )


@router.get("/oportunidades/{ren_id}", response_class=HTMLResponse)
def oportunidad_detalle(request: Request, ren_id: str, session: Session = Depends(get_session)):
    org = resolve_org(session)
    ren = session.get(RenewalOpportunity, ren_id)
    if ren is None or ren.organization_id != org.id:
        raise HTTPException(404, "oportunidad no encontrada")
    pol = session.get(Policy, ren.previous_policy_id)
    party = session.get(Party, pol.client_party_id) if pol else None
    carrier = session.get(Carrier, pol.carrier_id) if pol else None
    line = session.get(InsuranceLine, pol.insurance_line_id) if pol else None
    client_name = ""
    if party:
        client_name = " ".join(x for x in [party.first_name or "", party.last_name or ""] if x) or (
            party.legal_name or ""
        )
    quote_request_id = None
    for qr in session.query(QuoteRequest).filter_by(organization_id=org.id).all():
        try:
            payload = json.loads(qr.payload_json or "{}")
        except Exception:
            continue
        if payload.get("renewal_opportunity_id") == ren.id:
            quote_request_id = qr.id
            break
    carriers = (
        session.query(Carrier)
        .filter_by(organization_id=org.id, active=True)
        .order_by(Carrier.name)
        .all()
    )
    statuses = [
        "UPCOMING",
        "CONTACT_PENDING",
        "CONTACTED",
        "QUOTING",
        "PROPOSAL_SENT",
        "WAITING_CLIENT",
        "ACCEPTED",
        "RENEWED",
        "DECLINED",
        "LOST",
        "NON_RENEWED",
    ]
    return templates.TemplateResponse(
        request,
        "oportunidad_detalle.html",
        _ctx(
            request,
            "oportunidades",
            org_name=org.name,
            ren=ren,
            policy_number=pol.policy_number if pol else "—",
            client_name=client_name or "—",
            party_id=pol.client_party_id if pol else "",
            carrier_name=carrier.name if carrier else "—",
            current_carrier_id=carrier.id if carrier else "",
            line_code=line.code if line else "—",
            premium=(pol.annual_premium or pol.net_premium) if pol else None,
            carriers=carriers,
            statuses=statuses,
            quote_request_id=quote_request_id,
        ),
    )


@router.post("/oportunidades/{ren_id}/estado")
def oportunidad_estado_post(
    request: Request,
    ren_id: str,
    status: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    ren = session.get(RenewalOpportunity, ren_id)
    if ren is None or ren.organization_id != org.id:
        raise HTTPException(404)
    if status:
        advance_renewal_status(session, ren, status, actor_id=current_actor(request).actor_id)
    return RedirectResponse(f"/oportunidades/{ren_id}", status_code=303)


@router.post("/oportunidades/{ren_id}/misma-cia")
def oportunidad_misma_cia_post(
    request: Request, ren_id: str, session: Session = Depends(get_session)
):
    org = resolve_org(session)
    ren = session.get(RenewalOpportunity, ren_id)
    if ren is None or ren.organization_id != org.id:
        raise HTTPException(404)
    start_same_carrier_renewal(session, ren, actor_id=current_actor(request).actor_id)
    return RedirectResponse(f"/oportunidades/{ren_id}", status_code=303)


@router.post("/oportunidades/{ren_id}/recotizar")
def oportunidad_recotizar_post(
    request: Request,
    ren_id: str,
    carrier_ids: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    ren = session.get(RenewalOpportunity, ren_id)
    if ren is None or ren.organization_id != org.id:
        raise HTTPException(404)
    if isinstance(carrier_ids, str):
        carrier_ids = [carrier_ids]
    carrier_ids = [c for c in carrier_ids if c]
    if not carrier_ids:
        return RedirectResponse(f"/oportunidades/{ren_id}", status_code=303)
    _ren, qr, _cqrs = start_multi_carrier_recote(
        session, ren, carrier_ids=carrier_ids, actor_id=current_actor(request).actor_id
    )
    return RedirectResponse(f"/cotizador?quote_request_id={qr.id}", status_code=303)


@router.get("/referidos", response_class=HTMLResponse)
def referidos(request: Request, session: Session = Depends(get_session)):
    from corredores.services.commission_plan import build_commission_plan_view

    org = resolve_org(session)
    plan_view = build_commission_plan_view(session, org.id)
    return templates.TemplateResponse(
        request,
        "referidos.html",
        _ctx(
            request,
            "referidos",
            org_name=org.name,
            plan=plan_view.referral_plan,
            referral_total=plan_view.referral_total,
        ),
    )


@router.get("/aseguradoras", response_class=HTMLResponse)
def aseguradoras(
    request: Request,
    q: str = Query(default=""),
    activa: str = Query(default=""),
    session: Session = Depends(get_session),
):
    from corredores.services.catalog_admin import list_carriers

    org = resolve_org(session)
    needle = _q(q)
    activa_n = _q(activa).lower()
    rows = list_carriers(session, org.id)
    filtered = []
    for c in rows:
        if activa_n == "si" and not c.active:
            continue
        if activa_n == "no" and c.active:
            continue
        if not _match(f"{c.code} {c.name}", needle):
            continue
        filtered.append(c)
    edit_id = request.query_params.get("edit") or ""
    edit_row = next((c for c in rows if c.id == edit_id), None)
    if edit_row is not None and all(c.id != edit_row.id for c in filtered):
        filtered = [edit_row, *filtered]
    return templates.TemplateResponse(
        request,
        "aseguradoras.html",
        _ctx(
            request,
            "aseguradoras",
            org_name=org.name,
            carriers=filtered,
            q=needle,
            activa=activa_n,
            result_count=len(filtered),
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
            edit_id=edit_id,
            edit_row=edit_row,
        ),
    )


@router.post("/aseguradoras")
def aseguradoras_post(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    carrier_id: str = Form(""),
    active: str = Form(""),
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.catalog_admin import upsert_carrier

    org = resolve_org(session)
    actor = current_actor(request)
    try:
        row = upsert_carrier(
            session,
            organization_id=org.id,
            code=code,
            name=name,
            active=active.strip().lower() in {"1", "true", "on", "yes", "si"},
            carrier_id=carrier_id.strip() or None,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        return RedirectResponse(
            f"/aseguradoras?error={quote(str(exc))}", status_code=303
        )
    return RedirectResponse(f"/aseguradoras?ok=saved#row-{row.id}", status_code=303)


@router.get("/ramos", response_class=HTMLResponse)
def ramos(request: Request, session: Session = Depends(get_session)):
    from corredores.services.catalog_admin import list_lines

    org = resolve_org(session)
    lines = list_lines(session)
    edit_id = request.query_params.get("edit") or ""
    edit_row = next((l for l in lines if l.id == edit_id), None)
    return templates.TemplateResponse(
        request,
        "ramos.html",
        _ctx(
            request,
            "ramos",
            org_name=org.name,
            lines=lines,
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
            edit_id=edit_id,
            edit_row=edit_row,
        ),
    )


@router.post("/ramos")
def ramos_post(
    request: Request,
    code: str = Form(""),
    name: str = Form(""),
    line_id: str = Form(""),
    operational: str = Form(""),
    action: str = Form("save"),
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.catalog_admin import delete_line, upsert_line

    org = resolve_org(session)
    actor = current_actor(request)
    act = (action or "save").strip().lower()
    try:
        if act == "delete":
            lid = (line_id or "").strip()
            if not lid:
                raise ValueError("ramo no indicado")
            delete_line(
                session,
                organization_id=org.id,
                line_id=lid,
                actor_id=actor.actor_id,
            )
            return RedirectResponse("/ramos?ok=deleted", status_code=303)
        row = upsert_line(
            session,
            organization_id=org.id,
            code=code,
            name=name,
            operational_in_p0=operational.strip().lower() in {"1", "true", "on", "yes", "si"},
            line_id=line_id.strip() or None,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        return RedirectResponse(f"/ramos?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(f"/ramos?ok=saved#row-{row.id}", status_code=303)


def _require_producers_manage(session: Session, request: Request) -> None:
    """ADR-008 F4 — producers:manage when AccessContext is available."""
    from corredores.services.access_control import AccessDenied, require_permission
    from corredores.web.deps import current_access_context

    access = current_access_context(session, request)
    if access is None:
        return  # auth off / piloto
    try:
        require_permission(access, "producers:manage")
    except AccessDenied as e:
        raise HTTPException(403, "sin permiso para administrar productores") from e


@router.get("/productores", response_class=HTMLResponse)
def productores(request: Request, session: Session = Depends(get_session)):
    from corredores.services.producer_portfolio import (
        active_assignments_for_producer,
        list_producer_profiles,
    )
    from corredores.services.seats import seat_snapshot

    org = resolve_org(session)
    _require_producers_manage(session, request)
    profiles = list_producer_profiles(session, organization_id=org.id)
    rows = []
    for p in profiles:
        party = session.get(Party, p.party_id)
        n_active = len(
            active_assignments_for_producer(
                session, organization_id=org.id, producer_profile_id=p.id
            )
        )
        rows.append(
            {
                "profile": p,
                "email": party.email if party else None,
                "active_policies": n_active,
            }
        )
    seats = seat_snapshot(session, org.id)
    return templates.TemplateResponse(
        request,
        "productores.html",
        _ctx(
            request,
            "productores",
            org_name=org.name,
            rows=rows,
            seats=seats.public_dict(),
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
        ),
    )


@router.post("/productores")
def productores_create(
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    code: str = Form(""),
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.producer_portfolio import (
        ProducerPortfolioError,
        create_producer_person,
    )

    org = resolve_org(session)
    _require_producers_manage(session, request)
    try:
        profile = create_producer_person(
            session,
            organization_id=org.id,
            first_name=first_name,
            last_name=last_name,
            email=email or None,
            code=code or None,
        )
    except ProducerPortfolioError as exc:
        return RedirectResponse(f"/productores?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(f"/productores/{profile.id}?ok=created", status_code=303)


@router.get("/productores/{profile_id}", response_class=HTMLResponse)
def productor_detalle(
    profile_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    from corredores.domain.membership_roles import PRODUCER
    from corredores.domain.models import BrokerAccount, OrgMembership, ProducerProfile
    from corredores.services.producer_portfolio import active_assignments_for_producer
    from corredores.services.seats import seat_snapshot

    org = resolve_org(session)
    _require_producers_manage(session, request)
    profile = session.get(ProducerProfile, profile_id)
    if profile is None or profile.organization_id != org.id:
        raise HTTPException(404, "productor no encontrado")
    party = session.get(Party, profile.party_id)
    assignments = active_assignments_for_producer(
        session, organization_id=org.id, producer_profile_id=profile.id
    )
    portfolio = []
    for a in assignments:
        pol = session.get(Policy, a.target_id)
        client = None
        if pol and pol.client_party_id:
            client = session.get(Party, pol.client_party_id)
        client_name = None
        if client:
            client_name = " ".join(
                x for x in [client.first_name or "", client.last_name or ""] if x
            ).strip() or (client.legal_name or client.id[:8])
        portfolio.append(
            {
                "assignment": a,
                "policy": pol,
                "client_name": client_name,
            }
        )
    policies = (
        session.query(Policy)
        .filter_by(organization_id=org.id)
        .order_by(Policy.created_at.desc())
        .limit(300)
        .all()
    )
    access_membership = None
    if party and party.email:
        acc = (
            session.query(BrokerAccount)
            .filter(BrokerAccount.email == party.email.strip().lower())
            .one_or_none()
        )
        if acc:
            access_membership = (
                session.query(OrgMembership)
                .filter_by(
                    organization_id=org.id,
                    subject_id=acc.subject_id,
                    role_code=PRODUCER,
                    active=True,
                )
                .one_or_none()
            )
    seats = seat_snapshot(session, org.id)
    return templates.TemplateResponse(
        request,
        "productor_detalle.html",
        _ctx(
            request,
            "productores",
            org_name=org.name,
            profile=profile,
            party=party,
            portfolio=portfolio,
            policies=policies,
            access_membership=access_membership,
            seats=seats.public_dict(),
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
        ),
    )


@router.post("/productores/{profile_id}/acceso")
def productor_grant_access(
    profile_id: str,
    request: Request,
    account_email: str = Form(...),
    session: Session = Depends(get_session),
):
    """Grant PRODUCER system access (consumes producer_seat) — ADR-008 F5."""
    from urllib.parse import quote

    from corredores.domain.models import BrokerAccount, ProducerProfile
    from corredores.services.seats import SeatLimitError, grant_producer_system_access

    org = resolve_org(session)
    _require_producers_manage(session, request)
    profile = session.get(ProducerProfile, profile_id)
    if profile is None or profile.organization_id != org.id:
        raise HTTPException(404, "productor no encontrado")
    email = (account_email or "").strip().lower()
    acc = session.query(BrokerAccount).filter_by(email=email, active=True).one_or_none()
    if acc is None:
        return RedirectResponse(
            f"/productores/{profile_id}?error={quote('cuenta ESB no encontrada para ese email')}",
            status_code=303,
        )
    try:
        grant_producer_system_access(
            session,
            organization_id=org.id,
            producer_profile_id=profile.id,
            subject_id=acc.subject_id,
            display_name=profile.display_name,
        )
    except SeatLimitError as exc:
        return RedirectResponse(
            f"/productores/{profile_id}?error={quote(str(exc))}", status_code=303
        )
    return RedirectResponse(f"/productores/{profile_id}?ok=access", status_code=303)


@router.post("/productores/{profile_id}/asignar")
def productor_asignar(
    profile_id: str,
    request: Request,
    policy_id: str = Form(...),
    reason: str = Form(...),
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.domain.models import ProducerProfile
    from corredores.services.producer_portfolio import (
        ProducerPortfolioError,
        reassign_policy_primary,
    )

    org = resolve_org(session)
    actor = current_actor(request)
    _require_producers_manage(session, request)
    profile = session.get(ProducerProfile, profile_id)
    if profile is None or profile.organization_id != org.id:
        raise HTTPException(404, "productor no encontrado")
    try:
        reassign_policy_primary(
            session,
            organization_id=org.id,
            producer_profile_id=profile.id,
            policy_id=policy_id.strip(),
            reason=reason,
            assigned_by_subject_id=actor.actor_id,
        )
    except ProducerPortfolioError as exc:
        return RedirectResponse(
            f"/productores/{profile_id}?error={quote(str(exc))}", status_code=303
        )
    return RedirectResponse(f"/productores/{profile_id}?ok=assigned", status_code=303)


@router.get("/polizas/{policy_id}/productor", response_class=HTMLResponse)
def poliza_productor_historial(
    policy_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    from corredores.domain.models import ProducerProfile
    from corredores.services.producer_portfolio import (
        active_policy_primary,
        assignment_history_for_policy,
        list_producer_profiles,
    )

    org = resolve_org(session)
    _require_producers_manage(session, request)
    pol = session.get(Policy, policy_id)
    if pol is None or pol.organization_id != org.id:
        raise HTTPException(404, "póliza no encontrada")
    history = assignment_history_for_policy(
        session, organization_id=org.id, policy_id=pol.id
    )
    hist_rows = []
    for a in history:
        prod = session.get(ProducerProfile, a.producer_profile_id)
        hist_rows.append({"assignment": a, "producer": prod})
    current = active_policy_primary(
        session, organization_id=org.id, policy_id=pol.id
    )
    producers = list_producer_profiles(
        session, organization_id=org.id, include_inactive=False
    )
    return templates.TemplateResponse(
        request,
        "poliza_productor.html",
        _ctx(
            request,
            "productores",
            org_name=org.name,
            policy=pol,
            history=hist_rows,
            current=current,
            producers=producers,
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
        ),
    )


@router.post("/polizas/{policy_id}/productor")
def poliza_productor_reassign(
    policy_id: str,
    request: Request,
    producer_profile_id: str = Form(...),
    reason: str = Form(...),
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.producer_portfolio import (
        ProducerPortfolioError,
        reassign_policy_primary,
    )

    org = resolve_org(session)
    actor = current_actor(request)
    _require_producers_manage(session, request)
    pol = session.get(Policy, policy_id)
    if pol is None or pol.organization_id != org.id:
        raise HTTPException(404, "póliza no encontrada")
    try:
        reassign_policy_primary(
            session,
            organization_id=org.id,
            producer_profile_id=producer_profile_id.strip(),
            policy_id=pol.id,
            reason=reason,
            assigned_by_subject_id=actor.actor_id,
        )
    except ProducerPortfolioError as exc:
        return RedirectResponse(
            f"/polizas/{policy_id}/productor?error={quote(str(exc))}", status_code=303
        )
    return RedirectResponse(f"/polizas/{policy_id}/productor?ok=reassigned", status_code=303)


@router.get("/comisiones", response_class=HTMLResponse)
def comisiones(request: Request, session: Session = Depends(get_session)):
    from corredores.services.catalog_admin import get_split_for_edit, list_line_commission_rates
    from corredores.services.commission_plan import (
        build_commission_plan_view,
        list_applied_commissions,
    )

    org = resolve_org(session)
    plan = build_commission_plan_view(session, org.id)
    applied = list_applied_commissions(session, org.id)
    return templates.TemplateResponse(
        request,
        "comisiones.html",
        _ctx(
            request,
            "comisiones",
            org_name=org.name,
            plan=plan,
            applied=applied,
            rate_rows=list_line_commission_rates(session, org.id),
            split_edit=get_split_for_edit(session, org.id),
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
        ),
    )


@router.post("/comisiones/tasas")
async def comisiones_tasas_post(request: Request, session: Session = Depends(get_session)):
    from urllib.parse import quote

    from corredores.services.catalog_admin import save_all_line_rates

    org = resolve_org(session)
    actor = current_actor(request)
    form = await request.form()
    rates = {}
    for key in form.keys():
        if key.startswith("rate__"):
            rates[key[6:]] = str(form.get(key) or "")
    try:
        n = save_all_line_rates(
            session, organization_id=org.id, rates=rates, actor_id=actor.actor_id
        )
    except ValueError as exc:
        return RedirectResponse(f"/comisiones?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(
        f"/comisiones?ok={quote(f'{n} tasa(s) guardadas')}", status_code=303
    )


@router.post("/comisiones/reparto")
def comisiones_reparto_post(
    request: Request,
    broker_pct: str = Form(...),
    executive_pct: str = Form(...),
    office_pct: str = Form(...),
    referral_pct: str = Form(...),
    name: str = Form(""),
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.catalog_admin import save_split_shares

    org = resolve_org(session)
    actor = current_actor(request)
    try:
        save_split_shares(
            session,
            organization_id=org.id,
            broker_pct=broker_pct,
            executive_pct=executive_pct,
            office_pct=office_pct,
            referral_pct=referral_pct,
            name=name or None,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        return RedirectResponse(f"/comisiones?error={quote(str(exc))}", status_code=303)
    return RedirectResponse("/comisiones?ok=reparto%20guardado", status_code=303)


@router.get("/importaciones", response_class=HTMLResponse)
def importaciones_home(request: Request, session: Session = Depends(get_session)):
    from corredores.services.import_engine import profiles_by_module

    org = resolve_org(session)
    return templates.TemplateResponse(
        request,
        "importaciones.html",
        _ctx(
            request,
            "importaciones",
            org_name=org.name,
            by_module=profiles_by_module(),
            flash_ok=request.query_params.get("ok"),
            flash_err=request.query_params.get("error"),
        ),
    )


@router.get("/importaciones/{profile_id}", response_class=HTMLResponse)
def importaciones_perfil(
    request: Request, profile_id: str, session: Session = Depends(get_session)
):
    from corredores.services.import_engine import get_profile

    org = resolve_org(session)
    profile = get_profile(profile_id)
    if profile is None:
        raise HTTPException(404, "perfil de importación no encontrado")
    return templates.TemplateResponse(
        request,
        "importaciones_perfil.html",
        _ctx(
            request,
            "importaciones",
            org_name=org.name,
            profile=profile,
            preview=None,
            error=None,
        ),
    )


@router.post("/importaciones/{profile_id}/preview", response_class=HTMLResponse)
async def importaciones_preview(
    request: Request,
    profile_id: str,
    session: Session = Depends(get_session),
):
    from corredores.services.import_engine import get_profile, new_token, preview_profile

    org = resolve_org(session)
    profile = get_profile(profile_id)
    if profile is None:
        raise HTTPException(404, "perfil no encontrado")

    form = await request.form()
    token = new_token()
    files: dict[str, tuple[str, bytes]] = {}
    for key in list(profile.file_keys) + ["file", "pagos", "tablas"]:
        upload = form.get(key)
        if upload is None or not hasattr(upload, "read"):
            continue
        content = await upload.read()
        if not content and profile_id not in ("comisiones", "renovaciones"):
            continue
        name = getattr(upload, "filename", None) or f"{key}.xlsx"
        files[key] = (name, content)

    try:
        preview = preview_profile(profile_id, token=token, files=files)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "importaciones_perfil.html",
            _ctx(
                request,
                "importaciones",
                org_name=org.name,
                profile=profile,
                preview=None,
                error=str(exc),
            ),
            status_code=400,
        )
    return templates.TemplateResponse(
        request,
        "importaciones_perfil.html",
        _ctx(
            request,
            "importaciones",
            org_name=org.name,
            profile=profile,
            preview=preview,
            error=None,
        ),
    )


@router.post("/importaciones/{profile_id}/commit")
def importaciones_commit(
    request: Request,
    profile_id: str,
    token: str = Form(...),
    session: Session = Depends(get_session),
):
    from corredores.services.import_engine import commit_profile, get_profile

    org = resolve_org(session)
    actor = current_actor(request)
    if get_profile(profile_id) is None:
        raise HTTPException(404)
    try:
        result = commit_profile(
            session,
            profile_id=profile_id,
            token=token,
            organization_id=org.id,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        return RedirectResponse(
            f"/importaciones?error={str(exc).replace(' ', '+')}", status_code=303
        )
    except Exception:
        return RedirectResponse(
            "/importaciones?error=Fallo+al+importar", status_code=303
        )
    rep = result.get("report") or result.get("materialize") or {}
    msg = f"Importación+{profile_id}+OK"
    if isinstance(rep, dict):
        if rep.get("policies_created") is not None:
            msg = f"OK:+{rep.get('policies_created',0)}+pólizas+·+{rep.get('parties_upserted',0)}+personas"
        elif rep.get("payments_imported") is not None:
            msg = f"OK:+{rep.get('payments_imported',0)}+pagos"
        elif rep.get("commissions_created") is not None or "commissions" in str(rep):
            msg = "OK:+cartera+materializada"
    return RedirectResponse(f"/importaciones?ok={msg}", status_code=303)


@router.get("/documentos", response_class=HTMLResponse)
def documentos(
    request: Request,
    q: str = Query(default=""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    needle = _q(q)
    docs = list_org_documents(session, organization_id=org.id, q=needle)
    enriched = []
    for d in docs:
        party = session.get(Party, d.party_id) if d.party_id else None
        name = ""
        if party:
            name = " ".join(x for x in [party.first_name or "", party.last_name or ""] if x) or (
                party.legal_name or ""
            )
        enriched.append(
            {
                "id": d.id,
                "title": d.title,
                "filename": d.original_filename,
                "kind": d.doc_kind,
                "size": d.size_bytes,
                "created_at": d.created_at,
                "party_id": d.party_id,
                "party_name": name or "—",
            }
        )
    return templates.TemplateResponse(
        request,
        "documentos.html",
        _ctx(
            request,
            "documentos",
            org_name=org.name,
            documents=enriched,
            q=needle,
            result_count=len(enriched),
        ),
    )

@router.get("/oportunidades-ia", response_class=HTMLResponse)
def oportunidades_ia(request: Request):
    return _coming_soon(
        request,
        "oportunidades_ia",
        "Oportunidades IA",
        "NBA y sugerencias. Estudio 360° no vive aquí: se genera desde Cliente 360°.",
    )


@router.get("/reportes", response_class=HTMLResponse)
def reportes(
    request: Request,
    vista: str = Query(default="cobros"),
    session: Session = Depends(get_session),
):
    from decimal import Decimal

    from corredores.services.carrier_incentives import list_org_plans_with_progress

    org = resolve_org(session)
    summary = build_report_summary(session, org.id)
    preview = report_preview_rows(session, org.id)
    vista_n = (vista or "cobros").strip().lower()
    if vista_n not in {"cobros", "produccion", "metas", "descargas"}:
        vista_n = "cobros"

    metas_rows = list_org_plans_with_progress(session, org.id) if vista_n == "metas" else []
    confirmed = Decimal("0")
    benefit = Decimal("0")
    active_n = 0
    for row in metas_rows:
        if row["plan"].status == "ACTIVE":
            active_n += 1
        g = row.get("progress")
        if g is None:
            continue
        confirmed += g.confirmed_amount or Decimal("0")
        if g.benefit_stage == "EARNED":
            benefit += g.earned_benefit or Decimal("0")
        else:
            benefit += g.estimated_benefit or Decimal("0")
    metas = {
        "plans_total": len(metas_rows),
        "plans_active": active_n,
        "confirmed_total": confirmed,
        "benefit_total": benefit,
    }
    return templates.TemplateResponse(
        request,
        "reportes.html",
        _ctx(
            request,
            "reportes",
            org_name=org.name,
            summary=summary,
            preview=preview,
            today=date.today(),
            vista=vista_n,
            metas=metas,
            metas_rows=metas_rows,
            back_href="/hoy",
            back_label="← Hoy",
        ),
    )


def _reportes_imprimir_response(request: Request, session: Session, key: str):
    """PDF/print genérico con identidad de la correduría."""
    from datetime import datetime

    from corredores.services.org_identity import get_identity
    from corredores.services.reports import PRINT_REPORT_KEYS, build_print_report

    org = resolve_org(session)
    key_n = (key or "").strip().lower()
    if key_n not in PRINT_REPORT_KEYS:
        raise HTTPException(404, "reporte no encontrado")
    try:
        report = build_print_report(session, org.id, key_n)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    identity = get_identity(session, org.id)
    return templates.TemplateResponse(
        request,
        "print_reporte.html",
        {
            "request": request,
            "org_name": org.name,
            "identity": identity,
            "report": report,
            "as_of": date.today().isoformat(),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    )


@router.get("/reportes/cartera/imprimir", response_class=HTMLResponse)
def reportes_cartera_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "cartera")


@router.get("/reportes/cobranza/imprimir", response_class=HTMLResponse)
def reportes_cobranza_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "cobranza")


@router.get("/reportes/morosidad/imprimir", response_class=HTMLResponse)
def reportes_morosidad_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "morosidad")


@router.get("/reportes/renovaciones/imprimir", response_class=HTMLResponse)
def reportes_renovaciones_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "renovaciones")


@router.get("/reportes/pagos/imprimir", response_class=HTMLResponse)
def reportes_pagos_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "pagos")


@router.get("/reportes/comisiones/imprimir", response_class=HTMLResponse)
def reportes_comisiones_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "comisiones")


@router.get("/reportes/cotizaciones/imprimir", response_class=HTMLResponse)
def reportes_cotizaciones_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "cotizaciones")


@router.get("/reportes/clientes/imprimir", response_class=HTMLResponse)
def reportes_clientes_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "clientes")


@router.get("/reportes/reclamos/imprimir", response_class=HTMLResponse)
def reportes_reclamos_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "reclamos")


@router.get("/reportes/oportunidades/imprimir", response_class=HTMLResponse)
def reportes_oportunidades_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "oportunidades")


@router.get("/reportes/metas/imprimir", response_class=HTMLResponse)
def reportes_metas_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "metas")


@router.get("/reportes/referidos/imprimir", response_class=HTMLResponse)
def reportes_referidos_imprimir(request: Request, session: Session = Depends(get_session)):
    return _reportes_imprimir_response(request, session, "referidos")


@router.get("/reportes/cartera.csv")
def reportes_cartera_csv(session: Session = Depends(get_session)):
    org = resolve_org(session)
    body = csv_cartera(session, org.id)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cartera.csv"'},
    )


@router.get("/reportes/cobranza.csv")
def reportes_cobranza_csv(session: Session = Depends(get_session)):
    org = resolve_org(session)
    body = csv_cobranza(session, org.id)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cobranza.csv"'},
    )


@router.get("/reportes/renovaciones.csv")
def reportes_renovaciones_csv(session: Session = Depends(get_session)):
    org = resolve_org(session)
    body = csv_renovaciones(session, org.id)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="renovaciones.csv"'},
    )


@router.get("/reportes/pagos.csv")
def reportes_pagos_csv(session: Session = Depends(get_session)):
    org = resolve_org(session)
    body = csv_pagos(session, org.id)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="pagos_mes.csv"'},
    )


@router.get("/reportes/comisiones.csv")
def reportes_comisiones_csv(session: Session = Depends(get_session)):
    org = resolve_org(session)
    body = csv_comisiones(session, org.id)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="comisiones.csv"'},
    )


@router.get("/reportes/cotizaciones.csv")
def reportes_cotizaciones_csv(session: Session = Depends(get_session)):
    org = resolve_org(session)
    body = csv_cotizaciones(session, org.id)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cotizaciones.csv"'},
    )


@router.get("/reportes/morosidad.csv")
def reportes_morosidad_csv(
    aging: str = Query(default=""),
    session: Session = Depends(get_session),
):
    from corredores.services.account_cxc import csv_morosidad

    org = resolve_org(session)
    body = csv_morosidad(session, org.id, aging=_q(aging) or None)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="morosidad.csv"'},
    )


@router.get("/configuracion", response_class=HTMLResponse)
def configuracion(request: Request, session: Session = Depends(get_session)):
    from corredores.services.mail import mail_status
    from corredores.services.org_identity import get_identity
    from corredores.services.runtime_settings import runtime
    from corredores.services.statement_delivery import recent_deliveries

    org = resolve_org(session)
    deliveries = recent_deliveries(session, org.id, limit=40)
    party_ids = {d.party_id for d in deliveries}
    parties = (
        session.query(Party).filter(Party.id.in_(party_ids)).all() if party_ids else []
    )
    party_names = {}
    for p in parties:
        if getattr(p, "party_type", None) == "ORGANIZATION":
            party_names[p.id] = p.legal_name or p.trade_name or p.id
        else:
            party_names[p.id] = (
                " ".join(x for x in [p.first_name or "", p.last_name or ""] if x).strip()
                or p.id
            )
    mail = mail_status()
    cfg = runtime(session)
    setup = {
        "mail_ok": mail["configured"],
        "auto_ok": bool(mail["auto_enabled"] and mail["configured"]),
        "openai_ok": bool(cfg.get("capture.openai_api_key").strip()),
        "stripe_ok": bool(cfg.get("saas.stripe_secret_key").strip()),
        "onboarding_ok": bool(cfg.get("saas.onboarding_url").strip()),
    }
    return templates.TemplateResponse(
        request,
        "configuracion.html",
        _ctx(
            request,
            "configuracion",
            org_name=org.name,
            identity=get_identity(session, org.id),
            mail=mail,
            deliveries=deliveries,
            party_names=party_names,
            flash=request.query_params.get("ok"),
            flash_detail=request.query_params.get("detail"),
            dry_run=request.query_params.get("dry_run") == "1",
            auto_sent=request.query_params.get("sent", "0"),
            auto_skipped=request.query_params.get("skipped", "0"),
            auto_failed=request.query_params.get("failed", "0"),
            auto_outcomes=None,
            setup=setup,
        ),
    )


@router.post("/configuracion/identidad")
def configuracion_identidad_post(
    request: Request,
    name: str = Form(...),
    legal_name: str = Form(""),
    trade_name: str = Form(""),
    tax_id: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    website: str = Form(""),
    address: str = Form(""),
    slogan: str = Form(""),
    document_footer: str = Form(""),
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.org_identity import update_identity

    org = resolve_org(session)
    try:
        update_identity(
            session,
            org.id,
            name=name,
            legal_name=legal_name,
            trade_name=trade_name,
            tax_id=tax_id,
            phone=phone,
            email=email,
            website=website,
            address=address,
            slogan=slogan,
            document_footer=document_footer,
        )
        session.commit()
    except ValueError as exc:
        return RedirectResponse(
            f"/configuracion?ok=identity_err&detail={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse("/configuracion?ok=identity_ok", status_code=303)


@router.post("/configuracion/identidad/logo")
async def configuracion_identidad_logo(
    request: Request,
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.org_identity import save_logo

    org = resolve_org(session)
    form = await request.form()
    upload = form.get("logo")
    if upload is None or not hasattr(upload, "read"):
        return RedirectResponse(
            "/configuracion?ok=identity_err&detail=selecciona+un+archivo",
            status_code=303,
        )
    content = await upload.read()
    filename = getattr(upload, "filename", None) or "logo.png"
    try:
        save_logo(session, org.id, filename=filename, content=content)
        session.commit()
    except ValueError as exc:
        return RedirectResponse(
            f"/configuracion?ok=identity_err&detail={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse("/configuracion?ok=logo_ok", status_code=303)


@router.post("/configuracion/identidad/logo/eliminar")
def configuracion_identidad_logo_clear(
    request: Request, session: Session = Depends(get_session)
):
    from corredores.services.org_identity import clear_logo

    org = resolve_org(session)
    clear_logo(session, org.id)
    session.commit()
    return RedirectResponse("/configuracion?ok=logo_cleared", status_code=303)


@router.get("/configuracion/identidad/logo")
def configuracion_identidad_logo_get(
    request: Request, session: Session = Depends(get_session)
):
    from corredores.services.org_identity import get_identity, logo_absolute_path

    org = resolve_org(session)
    identity = get_identity(session, org.id)
    path = logo_absolute_path(identity) if identity else None
    if path is None:
        raise HTTPException(404, "sin logo")
    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)


@router.post("/configuracion/estados-auto")
def configuracion_estados_auto(
    request: Request,
    dry_run: str = Form("1"),
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.mail import mail_configured, mail_status
    from corredores.services.org_identity import get_identity
    from corredores.services.runtime_settings import runtime
    from corredores.services.statement_delivery import recent_deliveries, run_auto_statement_send

    org = resolve_org(session)
    is_dry = dry_run.strip() not in {"0", "false", "no"}
    cfg = runtime(session)
    if not is_dry and (not cfg.bool("statements.auto_enabled") or not mail_configured()):
        detail = quote(
            "Activa correo y estados auto en Mantenimiento",
            safe="",
        )
        return RedirectResponse(
            f"/configuracion?ok=auto_blocked&detail={detail}", status_code=303
        )
    report = run_auto_statement_send(session, org.id, dry_run=is_dry)
    if not is_dry:
        session.commit()

    # Dry-run: mostrar detalle en la misma pantalla (sin perder outcomes).
    if is_dry:
        deliveries = recent_deliveries(session, org.id, limit=40)
        party_ids = {d.party_id for d in deliveries}
        parties = (
            session.query(Party).filter(Party.id.in_(party_ids)).all() if party_ids else []
        )
        party_names = {}
        for p in parties:
            if getattr(p, "party_type", None) == "ORGANIZATION":
                party_names[p.id] = p.legal_name or p.trade_name or p.id
            else:
                party_names[p.id] = (
                    " ".join(x for x in [p.first_name or "", p.last_name or ""] if x).strip()
                    or p.id
                )
        return templates.TemplateResponse(
            request,
            "configuracion.html",
            _ctx(
                request,
                "configuracion",
                org_name=org.name,
                identity=get_identity(session, org.id),
                mail=mail_status(),
                deliveries=deliveries,
                party_names=party_names,
                flash="auto_ok",
                flash_detail=None,
                dry_run=True,
                auto_sent=str(report.sent),
                auto_skipped=str(report.skipped),
                auto_failed=str(report.failed),
                auto_outcomes=report.outcomes,
                setup=None,
            ),
        )

    return RedirectResponse(
        f"/configuracion?ok=auto_ok&dry_run=0"
        f"&sent={report.sent}&skipped={report.skipped}&failed={report.failed}",
        status_code=303,
    )


def _require_platform_admin(request: Request, session: Session):
    from corredores.services.tenant import is_platform_admin
    from corredores.web.auth_session import read_session

    principal = read_session(request)
    if principal is None:
        raise HTTPException(401, "sesión requerida")
    if not is_platform_admin(session, principal.actor_id, username=principal.username):
        raise HTTPException(403, "solo dueño de plataforma")
    return principal


@router.get("/mantenimiento", response_class=HTMLResponse)
def mantenimiento_get(request: Request, session: Session = Depends(get_session)):
    from corredores.services.runtime_settings import grouped_settings_for_ui

    _require_platform_admin(request, session)
    groups = grouped_settings_for_ui(session)
    return templates.TemplateResponse(
        request,
        "mantenimiento.html",
        _ctx(
            request,
            "mantenimiento",
            org_name="Plataforma",
            groups=groups,
            flash=request.query_params.get("ok"),
            flash_detail=request.query_params.get("detail"),
            error=request.query_params.get("error"),
        ),
    )


@router.post("/mantenimiento")
async def mantenimiento_post(request: Request, session: Session = Depends(get_session)):
    from urllib.parse import quote

    from corredores.services.runtime_settings import set_settings

    principal = _require_platform_admin(request, session)
    form = await request.form()
    updates: dict[str, str] = {}
    for key in form.keys():
        if key.startswith("s__"):
            updates[key[3:]] = str(form.get(key) or "")
    # unchecked bools don't appear — force false for known bool keys present as hidden markers
    for key in form.keys():
        if key.startswith("bool__"):
            real = key[6:]
            updates[real] = "true" if form.get(f"s__{real}") in {"on", "true", "1"} else "false"
    try:
        changed = set_settings(session, updates, actor_id=principal.actor_id)
    except ValueError as exc:
        return RedirectResponse(
            f"/mantenimiento?error={quote(str(exc))}", status_code=303
        )
    detail = quote(f"{len(changed)} cambio(s)", safe="")
    return RedirectResponse(f"/mantenimiento?ok=saved&detail={detail}", status_code=303)


@router.get("/mantenimiento/comprobantes", response_class=HTMLResponse)
def mantenimiento_comprobantes(
    request: Request,
    status: str = Query(default="pending"),
    session: Session = Depends(get_session),
):
    from corredores.services.saas_receipt_verify import list_receipts

    _require_platform_admin(request, session)
    st = (status or "pending").strip().lower()
    if st not in {"pending", "approved", "rejected", "all"}:
        st = "pending"
    rows = list_receipts(session, status=None if st == "all" else st)
    return templates.TemplateResponse(
        request,
        "mantenimiento_comprobantes.html",
        _ctx(
            request,
            "mantenimiento",
            org_name="Plataforma",
            rows=rows,
            status_filter=st,
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
        ),
    )


@router.get("/mantenimiento/comprobantes/{receipt_id}", response_class=HTMLResponse)
def mantenimiento_comprobante_detalle(
    receipt_id: str, request: Request, session: Session = Depends(get_session)
):
    from corredores.domain.models import Organization
    from corredores.services.saas_receipt_verify import get_receipt

    _require_platform_admin(request, session)
    row = get_receipt(session, receipt_id)
    if row is None:
        raise HTTPException(404, "comprobante no encontrado")
    org = session.get(Organization, row.organization_id)
    return templates.TemplateResponse(
        request,
        "mantenimiento_comprobante_detalle.html",
        _ctx(
            request,
            "mantenimiento",
            org_name="Plataforma",
            row=row,
            org=org,
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
        ),
    )


@router.get("/mantenimiento/comprobantes/{receipt_id}/archivo")
def mantenimiento_comprobante_archivo(
    receipt_id: str, request: Request, session: Session = Depends(get_session)
):
    from fastapi.responses import FileResponse

    from corredores.services.saas_receipt_verify import (
        ReceiptVerifyError,
        absolute_receipt_path,
        get_receipt,
    )

    _require_platform_admin(request, session)
    row = get_receipt(session, receipt_id)
    if row is None:
        raise HTTPException(404, "comprobante no encontrado")
    try:
        path = absolute_receipt_path(row)
    except ReceiptVerifyError as exc:
        raise HTTPException(404, str(exc)) from exc
    media = row.content_type or "application/octet-stream"
    return FileResponse(path, media_type=media, filename=row.original_filename)


@router.post("/mantenimiento/comprobantes/{receipt_id}/aprobar")
def mantenimiento_comprobante_aprobar(
    receipt_id: str,
    request: Request,
    note: str = Form(default=""),
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.saas_receipt_verify import ReceiptVerifyError, approve_receipt

    principal = _require_platform_admin(request, session)
    try:
        approve_receipt(
            session,
            receipt_id=receipt_id,
            reviewer_subject_id=principal.actor_id,
            note=note,
        )
    except ReceiptVerifyError as exc:
        return RedirectResponse(
            f"/mantenimiento/comprobantes/{receipt_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/mantenimiento/comprobantes/{receipt_id}?ok=approved", status_code=303
    )


@router.post("/mantenimiento/comprobantes/{receipt_id}/rechazar")
def mantenimiento_comprobante_rechazar(
    receipt_id: str,
    request: Request,
    note: str = Form(default=""),
    session: Session = Depends(get_session),
):
    from urllib.parse import quote

    from corredores.services.saas_receipt_verify import ReceiptVerifyError, reject_receipt

    principal = _require_platform_admin(request, session)
    try:
        reject_receipt(
            session,
            receipt_id=receipt_id,
            reviewer_subject_id=principal.actor_id,
            note=note,
        )
    except ReceiptVerifyError as exc:
        return RedirectResponse(
            f"/mantenimiento/comprobantes/{receipt_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/mantenimiento/comprobantes/{receipt_id}?ok=rejected", status_code=303
    )


@router.post("/nba/{rec_id}/decide")
def nba_decide(
    rec_id: str,
    decision: str = Form(...),
    session: Session = Depends(get_session),
):
    from corredores.domain.models import RecommendationRecord
    from corredores.services.tenant import require_org_owned

    org = resolve_org(session)
    actor = current_actor()
    rec = require_org_owned(
        session, RecommendationRecord, rec_id, org.id, not_found="recommendation not found"
    )
    decide_recommendation(
        session,
        rec,
        RecommendationDecision(decision),
        actor_id=actor.actor_id,
    )
    return RedirectResponse("/hoy", status_code=303)
