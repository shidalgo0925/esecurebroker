"""ADR-011 F4 — CRM Pipeline Web / Kanban (HTML UI, DEV).

Distinct from renewal queue at `/oportunidades` (RenewalOpportunity).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from corredores.domain.crm_constants import (
    ACTIVITY_TYPES,
    PIPELINE_KANBAN_CODES,
    PIPELINE_STAGE_LABELS_ES,
    PROSPECT_COMPANY,
    STAGE_LOST,
    STAGE_WON,
)
from corredores.services.access_control import AccessDenied, require_permission
from corredores.services.crm_access import PERM_CRM_MANAGE, PERM_CRM_READ
from corredores.services.crm_service import (
    CrmAmbiguousCustomer,
    CrmError,
    complete_activity,
    convert_opportunity_to_customer,
    create_activity,
    create_opportunity,
    create_prospect,
    get_opportunity,
    get_prospect,
    list_activities,
    list_lead_sources,
    list_lost_reasons,
    list_opportunities,
    list_prospects,
    list_stages,
    mark_lost,
    mark_won,
    reopen_opportunity,
    set_opportunity_stage,
)
from corredores.web.auth_session import read_session
from corredores.web.deps import current_access_context, get_session, resolve_org
from corredores.web.routes import _ctx, templates

router = APIRouter()


def _actor(request: Request) -> str | None:
    p = read_session(request)
    return p.actor_id if p else None


def _ctx_access(session: Session, request: Request):
    return current_access_context(session, request)


def _require_crm(session: Session, request: Request, *, manage: bool = False) -> None:
    access = current_access_context(session, request)
    if access is None:
        return
    if access.has_permission("platform:admin"):
        return
    code = PERM_CRM_MANAGE if manage else PERM_CRM_READ
    try:
        require_permission(access, code)
    except AccessDenied as e:
        raise HTTPException(403, "sin permiso para CRM") from e


def _prospect_label(row) -> str:
    if (row.prospect_type or "").upper() == PROSPECT_COMPANY:
        return row.company_name or "Empresa"
    parts = [p for p in (row.first_name, row.last_name) if p]
    return " ".join(parts) if parts else "Sin nombre"


def _money(raw: str) -> Decimal | None:
    s = (raw or "").strip().replace(",", "")
    if not s:
        return None
    try:
        v = Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise CrmError("prima estimada inválida") from exc
    if v <= 0:
        return None
    return v


def _err_redirect(path: str, exc: Exception) -> RedirectResponse:
    if isinstance(exc, AccessDenied):
        msg = "no encontrado" if exc.not_found else "sin permiso"
    elif isinstance(exc, CrmAmbiguousCustomer):
        msg = "cliente ambiguo — vinculá desde detalle"
    else:
        msg = str(exc) or "error"
    return RedirectResponse(f"{path}?error={quote(msg)}", status_code=303)


# --- Pipeline Kanban ---


@router.get("/crm", response_class=HTMLResponse)
def crm_pipeline(
    request: Request,
    session: Session = Depends(get_session),
    include_lost: str = Query(default=""),
    error: str = Query(default=""),
    ok: str = Query(default=""),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=False)
    access = _ctx_access(session, request)
    show_lost = include_lost in {"1", "true", "yes", "on"}
    stages = list_stages(session, access, org.id)
    kanban_codes = [s.code for s in stages if s.is_kanban] or list(PIPELINE_KANBAN_CODES)
    opps = list_opportunities(
        session, access, org.id, include_lost=show_lost
    )
    by_stage: dict[str, list] = {c: [] for c in kanban_codes}
    lost_rows: list = []
    prospect_cache: dict[str, str] = {}
    for o in opps:
        label = o.title
        if o.prospect_id:
            if o.prospect_id not in prospect_cache:
                try:
                    p = get_prospect(session, access, org.id, o.prospect_id)
                    prospect_cache[o.prospect_id] = _prospect_label(p)
                except AccessDenied:
                    prospect_cache[o.prospect_id] = "—"
            label = f"{o.title} · {prospect_cache[o.prospect_id]}"
        card = {
            "id": o.id,
            "title": o.title,
            "subtitle": prospect_cache.get(o.prospect_id or "", ""),
            "stage_code": o.stage_code,
            "premium": o.estimated_premium,
            "label": label,
            "initial": (
                (prospect_cache.get(o.prospect_id or "") or o.title or "?")[:1].upper()
            ),
            "prev_code": None,
            "next_code": None,
        }
        if o.stage_code in kanban_codes:
            idx = kanban_codes.index(o.stage_code)
            if idx > 0:
                card["prev_code"] = kanban_codes[idx - 1]
            if idx < len(kanban_codes) - 1:
                card["next_code"] = kanban_codes[idx + 1]
        if o.stage_code == STAGE_LOST:
            lost_rows.append(card)
        elif o.stage_code in by_stage:
            by_stage[o.stage_code].append(card)
        else:
            by_stage.setdefault(o.stage_code, []).append(card)

    columns = [
        {
            "code": code,
            "name": PIPELINE_STAGE_LABELS_ES.get(code, code),
            "cards": by_stage.get(code, []),
        }
        for code in kanban_codes
    ]
    return templates.TemplateResponse(
        request,
        "crm_pipeline.html",
        _ctx(
            request,
            "crm",
            org_name=org.name,
            columns=columns,
            lost_rows=lost_rows if show_lost else [],
            show_lost=show_lost,
            stage_labels=PIPELINE_STAGE_LABELS_ES,
            kanban_codes=kanban_codes,
            error=error or None,
            ok=ok or None,
        ),
    )


@router.post("/crm/oportunidades/{opp_id}/etapa")
def crm_opp_stage_post(
    opp_id: str,
    request: Request,
    stage_code: str = Form(...),
    lost_reason_id: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        code = (stage_code or "").upper()
        if code == STAGE_WON:
            mark_won(
                session,
                access,
                organization_id=org.id,
                opportunity_id=opp_id,
                actor_id=_actor(request),
            )
        elif code == STAGE_LOST:
            if not lost_reason_id:
                raise CrmError("elegí un motivo de pérdida")
            mark_lost(
                session,
                access,
                organization_id=org.id,
                opportunity_id=opp_id,
                lost_reason_id=lost_reason_id,
                actor_id=_actor(request),
            )
        else:
            set_opportunity_stage(
                session,
                access,
                organization_id=org.id,
                opportunity_id=opp_id,
                stage_code=code,
                actor_id=_actor(request),
            )
    except (CrmError, AccessDenied, ValueError) as exc:
        return _err_redirect("/crm", exc)
    return RedirectResponse(
        f"/crm?ok={quote('Etapa actualizada')}",
        status_code=303,
    )


# --- Prospects ---


@router.get("/crm/prospectos", response_class=HTMLResponse)
def crm_prospectos(
    request: Request,
    session: Session = Depends(get_session),
    error: str = Query(default=""),
    ok: str = Query(default=""),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=False)
    access = _ctx_access(session, request)
    rows = list_prospects(session, access, org.id)
    sources = list_lead_sources(session, access, org.id)
    return templates.TemplateResponse(
        request,
        "crm_prospectos.html",
        _ctx(
            request,
            "crm",
            org_name=org.name,
            rows=[
                {
                    "id": r.id,
                    "label": _prospect_label(r),
                    "type": r.prospect_type,
                    "status": r.status,
                    "email": r.email,
                    "phone": r.phone or r.mobile,
                    "id_number": r.identification_number,
                }
                for r in rows
            ],
            sources=sources,
            error=error or None,
            ok=ok or None,
        ),
    )


@router.post("/crm/prospectos")
def crm_prospectos_create(
    request: Request,
    prospect_type: str = Form("PERSON"),
    first_name: str = Form(""),
    last_name: str = Form(""),
    company_name: str = Form(""),
    identification_number: str = Form(""),
    phone: str = Form(""),
    mobile: str = Form(""),
    email: str = Form(""),
    source_id: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        row = create_prospect(
            session,
            access,
            organization_id=org.id,
            prospect_type=prospect_type,
            first_name=first_name or None,
            last_name=last_name or None,
            company_name=company_name or None,
            identification_number=identification_number or None,
            phone=phone or None,
            mobile=mobile or None,
            email=email or None,
            source_id=source_id or None,
            notes=notes or None,
            actor_id=_actor(request),
        )
    except (CrmError, AccessDenied, ValueError) as exc:
        return _err_redirect("/crm/prospectos", exc)
    return RedirectResponse(
        f"/crm/prospectos/{row.id}?ok={quote('Prospecto creado')}",
        status_code=303,
    )


@router.get("/crm/prospectos/{prospect_id}", response_class=HTMLResponse)
def crm_prospecto_detalle(
    prospect_id: str,
    request: Request,
    session: Session = Depends(get_session),
    error: str = Query(default=""),
    ok: str = Query(default=""),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=False)
    access = _ctx_access(session, request)
    try:
        row = get_prospect(session, access, org.id, prospect_id)
    except AccessDenied as exc:
        raise HTTPException(404 if exc.not_found else 403, str(exc) or "no encontrado") from exc
    opps = [
        o
        for o in list_opportunities(session, access, org.id, include_lost=True)
        if o.prospect_id == prospect_id
    ]
    activities = list_activities(session, access, org.id, prospect_id=prospect_id)
    return templates.TemplateResponse(
        request,
        "crm_prospecto_detalle.html",
        _ctx(
            request,
            "crm",
            org_name=org.name,
            prospect=row,
            label=_prospect_label(row),
            opportunities=opps,
            activities=activities,
            stage_labels=PIPELINE_STAGE_LABELS_ES,
            activity_types=sorted(ACTIVITY_TYPES),
            error=error or None,
            ok=ok or None,
        ),
    )


@router.post("/crm/prospectos/{prospect_id}/oportunidades")
def crm_prospecto_crear_opp(
    prospect_id: str,
    request: Request,
    title: str = Form(...),
    estimated_premium: str = Form(""),
    product_interest: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        opp = create_opportunity(
            session,
            access,
            organization_id=org.id,
            title=title,
            prospect_id=prospect_id,
            estimated_premium=_money(estimated_premium),
            product_interest=product_interest or None,
            notes=notes or None,
            actor_id=_actor(request),
        )
    except (CrmError, AccessDenied, ValueError) as exc:
        return _err_redirect(f"/crm/prospectos/{prospect_id}", exc)
    return RedirectResponse(
        f"/crm/oportunidades/{opp.id}?ok={quote('Oportunidad creada')}",
        status_code=303,
    )


@router.post("/crm/prospectos/{prospect_id}/actividades")
def crm_prospecto_actividad(
    prospect_id: str,
    request: Request,
    activity_type: str = Form("FOLLOW_UP"),
    title: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        create_activity(
            session,
            access,
            organization_id=org.id,
            prospect_id=prospect_id,
            activity_type=activity_type,
            title=title or None,
            notes=notes or None,
            actor_id=_actor(request),
        )
    except (CrmError, AccessDenied, ValueError) as exc:
        return _err_redirect(f"/crm/prospectos/{prospect_id}", exc)
    return RedirectResponse(
        f"/crm/prospectos/{prospect_id}?ok={quote('Actividad registrada')}",
        status_code=303,
    )


# --- Opportunity detail ---


@router.get("/crm/oportunidades/{opp_id}", response_class=HTMLResponse)
def crm_oportunidad_detalle(
    opp_id: str,
    request: Request,
    session: Session = Depends(get_session),
    error: str = Query(default=""),
    ok: str = Query(default=""),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=False)
    access = _ctx_access(session, request)
    try:
        opp = get_opportunity(session, access, org.id, opp_id)
    except AccessDenied as exc:
        raise HTTPException(404 if exc.not_found else 403, str(exc) or "no encontrado") from exc
    prospect = None
    if opp.prospect_id:
        try:
            prospect = get_prospect(session, access, org.id, opp.prospect_id)
        except AccessDenied:
            prospect = None
    stages = list_stages(session, access, org.id)
    lost_reasons = list_lost_reasons(session, access, org.id)
    activities = list_activities(session, access, org.id, opportunity_id=opp_id)
    return templates.TemplateResponse(
        request,
        "crm_oportunidad_detalle.html",
        _ctx(
            request,
            "crm",
            org_name=org.name,
            opp=opp,
            prospect=prospect,
            prospect_label=_prospect_label(prospect) if prospect else None,
            stages=stages,
            lost_reasons=lost_reasons,
            activities=activities,
            stage_labels=PIPELINE_STAGE_LABELS_ES,
            activity_types=sorted(ACTIVITY_TYPES),
            kanban_codes=list(PIPELINE_KANBAN_CODES),
            error=error or None,
            ok=ok or None,
        ),
    )


@router.post("/crm/oportunidades/{opp_id}/etapa-detalle")
def crm_opp_stage_detalle_post(
    opp_id: str,
    request: Request,
    stage_code: str = Form(...),
    lost_reason_id: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        code = (stage_code or "").upper()
        if code == STAGE_WON:
            mark_won(
                session,
                access,
                organization_id=org.id,
                opportunity_id=opp_id,
                actor_id=_actor(request),
            )
        elif code == STAGE_LOST:
            mark_lost(
                session,
                access,
                organization_id=org.id,
                opportunity_id=opp_id,
                lost_reason_id=lost_reason_id,
                actor_id=_actor(request),
            )
        else:
            set_opportunity_stage(
                session,
                access,
                organization_id=org.id,
                opportunity_id=opp_id,
                stage_code=code,
                actor_id=_actor(request),
            )
    except (CrmError, AccessDenied, ValueError) as exc:
        return _err_redirect(f"/crm/oportunidades/{opp_id}", exc)
    return RedirectResponse(
        f"/crm/oportunidades/{opp_id}?ok={quote('Etapa actualizada')}",
        status_code=303,
    )


@router.post("/crm/oportunidades/{opp_id}/reabrir")
def crm_opp_reopen(
    opp_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        reopen_opportunity(
            session,
            access,
            organization_id=org.id,
            opportunity_id=opp_id,
            actor_id=_actor(request),
        )
    except (CrmError, AccessDenied, ValueError) as exc:
        return _err_redirect(f"/crm/oportunidades/{opp_id}", exc)
    return RedirectResponse(
        f"/crm/oportunidades/{opp_id}?ok={quote('Oportunidad reabierta')}",
        status_code=303,
    )


@router.post("/crm/oportunidades/{opp_id}/convertir")
def crm_opp_convert(
    opp_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        opp, party, action = convert_opportunity_to_customer(
            session,
            access,
            organization_id=org.id,
            opportunity_id=opp_id,
            actor_id=_actor(request),
        )
    except (CrmError, AccessDenied, CrmAmbiguousCustomer, ValueError) as exc:
        return _err_redirect(f"/crm/oportunidades/{opp_id}", exc)
    return RedirectResponse(
        f"/crm/oportunidades/{opp.id}?ok={quote(f'Cliente {action}: {party.id[:8]}…')}",
        status_code=303,
    )


@router.post("/crm/oportunidades/{opp_id}/actividades")
def crm_opp_actividad(
    opp_id: str,
    request: Request,
    activity_type: str = Form("FOLLOW_UP"),
    title: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        create_activity(
            session,
            access,
            organization_id=org.id,
            opportunity_id=opp_id,
            activity_type=activity_type,
            title=title or None,
            notes=notes or None,
            actor_id=_actor(request),
        )
    except (CrmError, AccessDenied, ValueError) as exc:
        return _err_redirect(f"/crm/oportunidades/{opp_id}", exc)
    return RedirectResponse(
        f"/crm/oportunidades/{opp_id}?ok={quote('Actividad registrada')}",
        status_code=303,
    )


@router.post("/crm/actividades/{activity_id}/completar")
def crm_activity_complete(
    activity_id: str,
    request: Request,
    return_to: str = Form("/crm"),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    dest = return_to if return_to.startswith("/crm") else "/crm"
    try:
        complete_activity(
            session,
            access,
            organization_id=org.id,
            activity_id=activity_id,
            actor_id=_actor(request),
        )
    except (CrmError, AccessDenied, ValueError) as exc:
        return _err_redirect(dest, exc)
    return RedirectResponse(f"{dest}?ok={quote('Actividad completada')}", status_code=303)
