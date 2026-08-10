"""HTML routes for the 7 P0 surfaces."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from corredores.domain.enums import RecommendationDecision
from corredores.domain.models import Claim, Party, QuoteRequest, RenewalOpportunity
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

NAV = [
    ("hoy", "Hoy", "/hoy"),
    ("radar", "Radar", "/radar"),
    ("clientes", "Cliente 360°", "/clientes"),
    ("cobranza", "Cobranza", "/cobranza"),
    ("cotizador", "Cotizador", "/cotizador"),
    ("renovaciones", "Renovaciones", "/renovaciones"),
    ("reclamos", "Reclamos", "/reclamos"),
    ("ayuda", "Ayuda", "/ayuda"),
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


def _ctx(request: Request, active: str, **extra):
    actor = current_actor(request)
    base = {
        "request": request,
        "nav": NAV,
        "active": active,
        "actor_name": actor.display_name,
        "today": date.today().isoformat(),
    }
    base.update(extra)
    return base


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
    home = build_today_home(session, org.id, actor_name=actor.display_name or "Broker")
    return templates.TemplateResponse(
        request,
        "hoy.html",
        _ctx(request, "hoy", org_name=org.name, home=home),
    )


@router.get("/radar", response_class=HTMLResponse)
def radar(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session)
    snap = build_radar(session, org.id)
    return templates.TemplateResponse(request, "radar.html", _ctx(request, "radar", org_name=org.name, snap=snap),
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
    return templates.TemplateResponse(request, "clientes.html", _ctx(request, "clientes", org_name=org.name, parties=parties),
    )


@router.get("/clientes/{party_id}", response_class=HTMLResponse)
def cliente_360(request: Request, party_id: str, session: Session = Depends(get_session)):
    org = resolve_org(session)
    try:
        snap = build_client_360(session, org.id, party_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return templates.TemplateResponse(request, "cliente_360.html", _ctx(request, "clientes", org_name=org.name, snap=snap),
    )


@router.get("/cobranza", response_class=HTMLResponse)
def cobranza(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session)
    board = build_cobranza_board(session, org.id)
    order = ["INTERVENTION", "PROMISE", "BROKEN_PROMISE", "EXCEPTION", "AUTOMATIC"]
    return templates.TemplateResponse(request, "cobranza.html", _ctx(
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
    return templates.TemplateResponse(request, "cotizador.html", _ctx(
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
    return templates.TemplateResponse(request, "renovaciones.html", _ctx(request, "renovaciones", org_name=org.name, rows=rows),
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
    return templates.TemplateResponse(request, "reclamos.html", _ctx(request, "reclamos", org_name=org.name, rows=rows),
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
