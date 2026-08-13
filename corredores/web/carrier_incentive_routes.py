"""ADR-009 — Carrier Incentive Plans UI (DEV)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from corredores.domain.incentive_constants import (
    BASE_COLLECTED_PREMIUM,
    BASE_ISSUED_PRODUCTION,
    BENEFIT_FIXED,
    BENEFIT_PERCENTAGE,
    METRIC_COLLECTION,
    METRIC_PRODUCTION,
    SCOPE_LINE,
)
from corredores.domain.models import Carrier, CarrierIncentiveSettlement, InsuranceLine
from corredores.services.access_control import AccessDenied, require_permission
from corredores.services.carrier_incentives import (
    IncentiveError,
    activate_plan,
    add_evidence,
    add_scope,
    add_tier,
    compute_progress,
    confirm_eligible_txn,
    create_plan,
    get_plan,
    list_plans_for_carrier,
    list_tiers,
    mark_claimed,
    mark_paid,
    mark_recognized,
    register_eligible_txn,
    reverse_eligible_txn,
    upsert_calculated_settlement,
)
from corredores.services.catalog_admin import list_lines
from corredores.web.deps import current_access_context, get_session, resolve_org
from corredores.web.routes import _ctx, templates

router = APIRouter()


def _actor(request: Request) -> str | None:
    from corredores.web.auth_session import read_session

    p = read_session(request)
    return p.actor_id if p else None


def _require_incentives(session: Session, request: Request, manage: bool = False) -> None:
    access = current_access_context(session, request)
    if access is None:
        return
    # Platform admin acting inside a tenant org (support / demos).
    if access.has_permission("platform:admin"):
        return
    code = "incentives:manage" if manage else "incentives:read"
    try:
        require_permission(access, code)
    except AccessDenied as e:
        raise HTTPException(403, "sin permiso para incentivos de aseguradora") from e


def _carrier_or_404(session: Session, organization_id: str, carrier_id: str) -> Carrier:
    c = session.get(Carrier, carrier_id)
    if c is None or c.organization_id != organization_id:
        raise HTTPException(404, "aseguradora no encontrada")
    return c


@router.get("/aseguradoras/{carrier_id}/beneficios", response_class=HTMLResponse)
def beneficios_list(
    carrier_id: str, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    _require_incentives(session, request, manage=False)
    carrier = _carrier_or_404(session, org.id, carrier_id)
    plans = list_plans_for_carrier(session, organization_id=org.id, carrier_id=carrier_id)
    rows = []
    for p in plans:
        try:
            prog = compute_progress(session, organization_id=org.id, plan_id=p.id)
        except IncentiveError:
            prog = None
        rows.append({"plan": p, "progress": prog})
    return templates.TemplateResponse(
        request,
        "carrier_beneficios.html",
        _ctx(
            request,
            "aseguradoras",
            org_name=org.name,
            carrier=carrier,
            rows=rows,
            lines=list_lines(session),
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
        ),
    )


@router.post("/aseguradoras/{carrier_id}/beneficios")
def beneficios_create(
    carrier_id: str,
    request: Request,
    name: str = Form(...),
    metric_type: str = Form(METRIC_COLLECTION),
    period_start: str = Form(...),
    period_end: str = Form(...),
    calculation_base: str = Form(BASE_COLLECTED_PREMIUM),
    description: str = Form(""),
    threshold_amount: str = Form("200000"),
    benefit_type: str = Form(BENEFIT_PERCENTAGE),
    benefit_value: str = Form("2"),
    line_id: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_incentives(session, request, manage=True)
    _carrier_or_404(session, org.id, carrier_id)
    try:
        plan = create_plan(
            session,
            organization_id=org.id,
            carrier_id=carrier_id,
            name=name,
            metric_type=metric_type,
            period_start=date.fromisoformat(period_start),
            period_end=date.fromisoformat(period_end),
            calculation_base=calculation_base
            or (
                BASE_COLLECTED_PREMIUM
                if metric_type == METRIC_COLLECTION
                else BASE_ISSUED_PRODUCTION
            ),
            description=description or None,
            actor_id=_actor(request),
        )
        add_tier(
            session,
            organization_id=org.id,
            plan_id=plan.id,
            threshold_amount=threshold_amount,
            benefit_type=benefit_type,
            benefit_value=benefit_value,
            actor_id=_actor(request),
        )
        if line_id.strip():
            add_scope(
                session,
                organization_id=org.id,
                plan_id=plan.id,
                scope_kind=SCOPE_LINE,
                insurance_line_id=line_id.strip(),
                actor_id=_actor(request),
            )
        activate_plan(
            session, organization_id=org.id, plan_id=plan.id, actor_id=_actor(request)
        )
    except (IncentiveError, ValueError, InvalidOperation) as exc:
        return RedirectResponse(
            f"/aseguradoras/{carrier_id}/beneficios?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/aseguradoras/{carrier_id}/beneficios/{plan.id}?ok=created", status_code=303
    )


@router.get("/aseguradoras/{carrier_id}/beneficios/{plan_id}", response_class=HTMLResponse)
def beneficio_detalle(
    carrier_id: str,
    plan_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_incentives(session, request, manage=False)
    carrier = _carrier_or_404(session, org.id, carrier_id)
    plan = get_plan(session, org.id, plan_id)
    if plan is None or plan.carrier_id != carrier_id:
        raise HTTPException(404, "plan no encontrado")
    progress = compute_progress(session, organization_id=org.id, plan_id=plan_id)
    tiers = list_tiers(session, org.id, plan_id)
    from corredores.domain.models import CarrierIncentiveEligibleTxn

    txns = (
        session.query(CarrierIncentiveEligibleTxn)
        .filter_by(organization_id=org.id, plan_id=plan_id)
        .order_by(CarrierIncentiveEligibleTxn.txn_date.desc())
        .limit(100)
        .all()
    )
    settlements = (
        session.query(CarrierIncentiveSettlement)
        .filter_by(organization_id=org.id, plan_id=plan_id)
        .order_by(CarrierIncentiveSettlement.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "carrier_beneficio_detalle.html",
        _ctx(
            request,
            "aseguradoras",
            org_name=org.name,
            carrier=carrier,
            plan=plan,
            progress=progress,
            tiers=tiers,
            txns=txns,
            settlements=settlements,
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
        ),
    )


@router.post("/aseguradoras/{carrier_id}/beneficios/{plan_id}/txn")
def beneficio_add_txn(
    carrier_id: str,
    plan_id: str,
    request: Request,
    amount: str = Form(...),
    txn_date: str = Form(...),
    source_id: str = Form(...),
    confirmation_status: str = Form("PENDING"),
    carrier_receipt_number: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_incentives(session, request, manage=True)
    plan = get_plan(session, org.id, plan_id)
    if plan is None or plan.carrier_id != carrier_id:
        raise HTTPException(404, "plan no encontrado")
    try:
        register_eligible_txn(
            session,
            organization_id=org.id,
            plan_id=plan_id,
            amount=amount,
            txn_date=date.fromisoformat(txn_date),
            source_type="MANUAL",
            source_id=source_id.strip(),
            carrier_id=carrier_id,
            confirmation_status=confirmation_status,
            carrier_receipt_number=carrier_receipt_number or None,
            actor_id=_actor(request),
        )
        upsert_calculated_settlement(
            session, organization_id=org.id, plan_id=plan_id, actor_id=_actor(request)
        )
    except (IncentiveError, ValueError) as exc:
        return RedirectResponse(
            f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?ok=txn", status_code=303
    )


@router.post("/aseguradoras/{carrier_id}/beneficios/{plan_id}/txn/{txn_id}/confirmar")
def beneficio_confirm_txn(
    carrier_id: str,
    plan_id: str,
    txn_id: str,
    request: Request,
    carrier_receipt_number: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_incentives(session, request, manage=True)
    try:
        confirm_eligible_txn(
            session,
            organization_id=org.id,
            txn_id=txn_id,
            carrier_receipt_number=carrier_receipt_number or None,
            actor_id=_actor(request),
        )
        upsert_calculated_settlement(
            session, organization_id=org.id, plan_id=plan_id, actor_id=_actor(request)
        )
    except IncentiveError as exc:
        return RedirectResponse(
            f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?ok=confirmed", status_code=303
    )


@router.post("/aseguradoras/{carrier_id}/beneficios/{plan_id}/txn/{txn_id}/reversar")
def beneficio_reverse_txn(
    carrier_id: str,
    plan_id: str,
    txn_id: str,
    request: Request,
    reason: str = Form("reverso"),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_incentives(session, request, manage=True)
    try:
        reverse_eligible_txn(
            session,
            organization_id=org.id,
            txn_id=txn_id,
            reason=reason,
            actor_id=_actor(request),
        )
        upsert_calculated_settlement(
            session, organization_id=org.id, plan_id=plan_id, actor_id=_actor(request)
        )
    except IncentiveError as exc:
        return RedirectResponse(
            f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?ok=reversed", status_code=303
    )


@router.post("/aseguradoras/{carrier_id}/beneficios/{plan_id}/reclamar")
def beneficio_reclamar(
    carrier_id: str,
    plan_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_incentives(session, request, manage=True)
    try:
        s = upsert_calculated_settlement(
            session, organization_id=org.id, plan_id=plan_id, actor_id=_actor(request)
        )
        mark_claimed(
            session, organization_id=org.id, settlement_id=s.id, actor_id=_actor(request)
        )
    except IncentiveError as exc:
        return RedirectResponse(
            f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?ok=claimed", status_code=303
    )


@router.post("/aseguradoras/{carrier_id}/beneficios/{plan_id}/reconocer")
def beneficio_reconocer(
    carrier_id: str,
    plan_id: str,
    request: Request,
    settlement_id: str = Form(...),
    recognized_amount: str = Form(...),
    carrier_reference: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_incentives(session, request, manage=True)
    try:
        mark_recognized(
            session,
            organization_id=org.id,
            settlement_id=settlement_id,
            recognized_amount=recognized_amount,
            carrier_reference=carrier_reference or None,
            actor_id=_actor(request),
        )
    except IncentiveError as exc:
        return RedirectResponse(
            f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?ok=recognized", status_code=303
    )


@router.post("/aseguradoras/{carrier_id}/beneficios/{plan_id}/pagado")
def beneficio_pagado(
    carrier_id: str,
    plan_id: str,
    request: Request,
    settlement_id: str = Form(...),
    paid_amount: str = Form(...),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_incentives(session, request, manage=True)
    try:
        mark_paid(
            session,
            organization_id=org.id,
            settlement_id=settlement_id,
            paid_amount=paid_amount,
            actor_id=_actor(request),
        )
    except IncentiveError as exc:
        return RedirectResponse(
            f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?ok=paid", status_code=303
    )


@router.post("/aseguradoras/{carrier_id}/beneficios/{plan_id}/evidencia")
def beneficio_evidencia(
    carrier_id: str,
    plan_id: str,
    request: Request,
    title: str = Form(...),
    evidence_kind: str = Form("OTRO"),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_incentives(session, request, manage=True)
    try:
        add_evidence(
            session,
            organization_id=org.id,
            plan_id=plan_id,
            title=title,
            evidence_kind=evidence_kind,
            notes=notes or None,
            actor_id=_actor(request),
        )
    except IncentiveError as exc:
        return RedirectResponse(
            f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/aseguradoras/{carrier_id}/beneficios/{plan_id}?ok=evidence", status_code=303
    )
