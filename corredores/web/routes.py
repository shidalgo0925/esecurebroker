"""Piloto shell — sidebar navigation (UX_NAV_SIDEBAR_V1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from corredores.domain.enums import RecommendationDecision
from corredores.domain.models import Carrier, Claim, InsuranceLine, Party, Policy, QuoteRequest, RenewalOpportunity
from corredores.services.client_360 import build_client_360
from corredores.services.cobranza_board import build_cobranza_board
from corredores.services.quote_orchestrator import build_comparator
from corredores.services.radar import build_radar
from corredores.services.recommendations import decide_recommendation
from corredores.web.deps import (
    current_actor,
    entitlements,
    get_session,
    resolve_org,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["money"] = lambda v: f"{Decimal(str(v)):.2f}"

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
            ("clientes", "Clientes", "/clientes", "users"),
            ("polizas", "Pólizas", "/polizas", "folder"),
            ("cobranza", "Cobranza", "/cobranza", "coins"),
            ("renovaciones", "Renovaciones", "/renovaciones", "refresh"),
            ("reclamos", "Reclamos", "/reclamos", "shield"),
        ],
    },
    {
        "title": "Ventas",
        "links": [
            ("oportunidades", "Oportunidades / CRM", "/oportunidades", "target"),
            ("cotizador", "Cotizador", "/cotizador", "scale"),
            ("referidos", "Referidos", "/referidos", "share"),
        ],
    },
    {
        "title": "Gestión",
        "links": [
            ("aseguradoras", "Aseguradoras", "/aseguradoras", "building"),
            ("comisiones", "Comisiones", "/comisiones", "percent"),
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
    ("ayuda", "Ayuda", "/ayuda", "help"),
]

NUEVA_GESTION = [
    ("Nueva póliza", "/polizas/nueva", "folder-plus"),
    ("Nuevo cliente", "/clientes/nuevo", "user-plus"),
    ("Nueva cotización", "/cotizador", "scale"),
    ("Registrar pago", "/cobranza", "coins"),
    ("Nuevo reclamo", "/reclamos/nuevo", "shield"),
]

BAND_LABELS = {
    "AUTOMATIC": "Rutinario (automático)",
    "INTERVENTION": "Requiere intervención",
    "PROMISE": "Promesa de pago",
    "BROKEN_PROMISE": "Promesa incumplida",
    "EXCEPTION": "Excepción",
}
BAND_HELP = {
    "AUTOMATIC": "el sistema lo lleva",
    "INTERVENTION": "tú actúas",
    "PROMISE": "compromiso activo",
    "BROKEN_PROMISE": "no cumplió",
    "EXCEPTION": "caso especial",
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


def _ctx(request: Request, active: str, **extra):
    actor = current_actor(request)
    collapsed = request.cookies.get("sidebar") == "collapsed"
    base = {
        "request": request,
        "nav_groups": NAV_GROUPS,
        "nav_footer": NAV_FOOTER,
        "nueva_gestion": NUEVA_GESTION,
        "active": active,
        "actor_name": actor.display_name,
        "today": date.today().isoformat(),
        "sidebar_collapsed": collapsed,
    }
    base.update(extra)
    return base


def _coming_soon(request: Request, active: str, title: str, blurb: str):
    return templates.TemplateResponse(
        request,
        "coming_soon.html",
        _ctx(request, active, page_title=title, blurb=blurb),
    )


@router.get("/", response_class=HTMLResponse)
def home():
    return RedirectResponse("/hoy", status_code=303)


@router.get("/ayuda", response_class=HTMLResponse)
def ayuda(request: Request):
    return templates.TemplateResponse(request, "ayuda.html", _ctx(request, "ayuda"))


@router.get("/hoy", response_class=HTMLResponse)
def hoy(request: Request, session: Session = Depends(get_session)):
    if not entitlements().has("any", "corredores.p0.auto"):
        raise HTTPException(403, "entitlement denied")
    from corredores.services.today_home import build_today_home

    org = resolve_org(session)
    actor = current_actor(request)
    home_snap = build_today_home(session, org.id, actor_name=actor.display_name or "Broker")
    return templates.TemplateResponse(
        request,
        "hoy.html",
        _ctx(request, "hoy", org_name=org.name, home=home_snap),
    )


@router.get("/radar", response_class=HTMLResponse)
def radar(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session)
    snap = build_radar(session, org.id)
    return templates.TemplateResponse(
        request, "radar.html", _ctx(request, "radar", org_name=org.name, snap=snap)
    )


@router.get("/clientes", response_class=HTMLResponse)
def clientes(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session)
    parties = (
        session.query(Party)
        .filter_by(organization_id=org.id)
        .order_by(Party.created_at.desc())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse(
        request, "clientes.html", _ctx(request, "clientes", org_name=org.name, parties=parties)
    )


@router.get("/clientes/nuevo", response_class=HTMLResponse)
def cliente_nuevo(request: Request):
    return templates.TemplateResponse(request, "cliente_nuevo.html", _ctx(request, "clientes"))


@router.post("/clientes/nuevo")
def cliente_nuevo_post(
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    national_id: str = Form(""),
    phone: str = Form(""),
    session: Session = Depends(get_session),
):
    from corredores.domain.enums import DataSource, PartyType

    org = resolve_org(session)
    party = Party(
        organization_id=org.id,
        party_type=PartyType.PERSON,
        first_name=first_name.strip() or None,
        last_name=last_name.strip() or None,
        national_id=national_id.strip() or None,
        phone=phone.strip() or None,
        data_source=DataSource.MANUAL,
    )
    session.add(party)
    session.flush()
    return RedirectResponse(f"/clientes/{party.id}", status_code=303)


@router.get("/clientes/{party_id}", response_class=HTMLResponse)
def cliente_360(request: Request, party_id: str, session: Session = Depends(get_session)):
    org = resolve_org(session)
    try:
        snap = build_client_360(session, org.id, party_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return templates.TemplateResponse(
        request, "cliente_360.html", _ctx(request, "clientes", org_name=org.name, snap=snap)
    )


@router.get("/polizas", response_class=HTMLResponse)
def polizas(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session)
    rows = (
        session.query(Policy)
        .filter_by(organization_id=org.id)
        .order_by(Policy.created_at.desc())
        .limit(100)
        .all()
    )
    enriched = []
    for p in rows:
        party = session.get(Party, p.client_party_id)
        carrier = session.get(Carrier, p.carrier_id)
        line = session.get(InsuranceLine, p.insurance_line_id)
        name = ""
        if party:
            name = " ".join(x for x in [party.first_name or "", party.last_name or ""] if x) or (
                party.legal_name or ""
            )
        enriched.append(
            {
                "id": p.id,
                "number": p.policy_number,
                "status": p.status,
                "client": name or "—",
                "party_id": p.client_party_id,
                "carrier": carrier.name if carrier else "—",
                "line": line.code if line else "—",
                "premium": p.annual_premium or p.net_premium,
            }
        )
    return templates.TemplateResponse(
        request,
        "polizas.html",
        _ctx(request, "polizas", org_name=org.name, policies=enriched),
    )


@router.get("/polizas/nueva", response_class=HTMLResponse)
def poliza_nueva(
    request: Request,
    step: str = Query(default="cliente"),
    quote_request_id: str | None = Query(default=None),
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
        .limit(50)
        .all()
    )
    carriers = session.query(Carrier).filter_by(organization_id=org.id).all()
    lines = session.query(InsuranceLine).order_by(InsuranceLine.code).all()
    from_quote = bool(quote_request_id)
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
            quote_request_id=quote_request_id,
        ),
    )


@router.post("/polizas/nueva")
def poliza_nueva_post(
    request: Request,
    party_id: str = Form(""),
    carrier_id: str = Form(""),
    line_id: str = Form(""),
    policy_number: str = Form(""),
    make: str = Form(""),
    model: str = Form(""),
    plate: str = Form(""),
    year: str = Form(""),
    effective_date: str = Form(""),
    expiration_date: str = Form(""),
    annual_premium: str = Form(""),
    num_payments: str = Form("12"),
    quote_request_id: str = Form(""),
    session: Session = Depends(get_session),
):
    """Registrar póliza — si quote_request_id viene, el UI ya marcó reutilización (sin re-captura conceptual)."""
    from datetime import date as date_cls

    from corredores.domain.enums import DataSource, DueDateSource, PolicyStatus, TermSource
    from corredores.domain.models import Installment, PaymentPlan, PolicyTerm, VehicleRisk
    from corredores.services.auto_e2e import ensure_auto_line, generate_proposed_installments, suggest_policy_term

    org = resolve_org(session)
    if not party_id or not carrier_id:
        raise HTTPException(400, "Cliente y aseguradora son obligatorios")

    line = session.get(InsuranceLine, line_id) if line_id else ensure_auto_line(session)
    if line is None:
        line = ensure_auto_line(session)

    eff = date_cls.fromisoformat(effective_date) if effective_date else date_cls.today()
    exp_in = date_cls.fromisoformat(expiration_date) if expiration_date else None
    eff, exp, term_src = suggest_policy_term(
        eff, expiration_date=exp_in, term_source=TermSource.MANUAL if exp_in else TermSource.SYSTEM_GENERATED
    )
    premium = Decimal(annual_premium or "0")
    n_pay = int(num_payments or "12")

    policy = Policy(
        organization_id=org.id,
        carrier_id=carrier_id,
        insurance_line_id=line.id,
        policy_number=policy_number.strip() or None,
        status=PolicyStatus.ACTIVE,
        client_party_id=party_id,
        annual_premium=premium if premium > 0 else None,
        net_premium=premium if premium > 0 else None,
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
            )
        )
    if premium > 0 and n_pay >= 1:
        plan = PaymentPlan(policy_id=policy.id, confirmed=True, notes="alta manual")
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
    return RedirectResponse("/polizas", status_code=303)


@router.get("/cobranza", response_class=HTMLResponse)
def cobranza(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session)
    board = build_cobranza_board(session, org.id)
    order = ["INTERVENTION", "PROMISE", "BROKEN_PROMISE", "EXCEPTION", "AUTOMATIC"]
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
        ),
    )


@router.get("/cotizador", response_class=HTMLResponse)
def cotizador(
    request: Request,
    quote_request_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    org = resolve_org(session)
    quotes = (
        session.query(QuoteRequest)
        .filter_by(organization_id=org.id)
        .order_by(QuoteRequest.created_at.desc())
        .limit(30)
        .all()
    )
    comparator = None
    if quote_request_id:
        try:
            comparator = build_comparator(session, quote_request_id)
        except Exception:
            comparator = None
    return templates.TemplateResponse(
        request,
        "cotizador.html",
        _ctx(
            request,
            "cotizador",
            org_name=org.name,
            quotes=quotes,
            comparator=comparator,
            selected_id=quote_request_id,
        ),
    )


@router.get("/renovaciones", response_class=HTMLResponse)
def renovaciones(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session)
    rows = (
        session.query(RenewalOpportunity)
        .filter_by(organization_id=org.id)
        .order_by(RenewalOpportunity.target_date)
        .limit(100)
        .all()
    )
    return templates.TemplateResponse(
        request, "renovaciones.html", _ctx(request, "renovaciones", org_name=org.name, rows=rows)
    )


@router.get("/reclamos", response_class=HTMLResponse)
def reclamos(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session)
    rows = (
        session.query(Claim)
        .filter_by(organization_id=org.id)
        .order_by(Claim.created_at.desc())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse(
        request, "reclamos.html", _ctx(request, "reclamos", org_name=org.name, rows=rows)
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
def oportunidades(request: Request):
    return _coming_soon(
        request,
        "oportunidades",
        "Oportunidades / CRM",
        "Pipeline comercial (leads → cotización → ganado/perdido). No reemplaza Hoy ni Radar.",
    )


@router.get("/referidos", response_class=HTMLResponse)
def referidos(request: Request):
    return _coming_soon(request, "referidos", "Referidos", "Red de referidos del corredor.")


@router.get("/aseguradoras", response_class=HTMLResponse)
def aseguradoras(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session)
    rows = session.query(Carrier).filter_by(organization_id=org.id).order_by(Carrier.name).all()
    return templates.TemplateResponse(
        request, "aseguradoras.html", _ctx(request, "aseguradoras", org_name=org.name, carriers=rows)
    )


@router.get("/comisiones", response_class=HTMLResponse)
def comisiones(request: Request):
    return _coming_soon(
        request,
        "comisiones",
        "Comisiones",
        "Reglas y liquidaciones — el dominio CommissionRule ya está sembrado (cli seed).",
    )


@router.get("/documentos", response_class=HTMLResponse)
def documentos(request: Request):
    return _coming_soon(request, "documentos", "Documentos", "Expediente documental por póliza / reclamo.")


@router.get("/oportunidades-ia", response_class=HTMLResponse)
def oportunidades_ia(request: Request):
    return _coming_soon(
        request,
        "oportunidades_ia",
        "Oportunidades IA",
        "NBA y sugerencias. Estudio 360° no vive aquí: se genera desde Cliente 360°.",
    )


@router.get("/reportes", response_class=HTMLResponse)
def reportes(request: Request):
    return _coming_soon(request, "reportes", "Reportes", "Reportes operativos y gerenciales.")


@router.get("/configuracion", response_class=HTMLResponse)
def configuracion(request: Request):
    return _coming_soon(
        request,
        "configuracion",
        "Configuración",
        "Preferencias de la organización. Identidad EN1 llega con ADR-006.",
    )


@router.post("/nba/{rec_id}/decide")
def nba_decide(
    rec_id: str,
    decision: str = Form(...),
    session: Session = Depends(get_session),
):
    from corredores.domain.models import RecommendationRecord

    actor = current_actor()
    rec = session.get(RecommendationRecord, rec_id)
    if rec is None:
        raise HTTPException(404, "recommendation not found")
    decide_recommendation(
        session,
        rec,
        RecommendationDecision(decision),
        actor_id=actor.actor_id,
    )
    return RedirectResponse("/hoy", status_code=303)
