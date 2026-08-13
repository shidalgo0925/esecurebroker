"""ADR-011 F4 — CRM Pipeline Web / Kanban (HTML UI, DEV).

Distinct from renewal queue at `/oportunidades` (RenewalOpportunity).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from corredores.domain.crm_constants import (
    ACTIVITY_TYPES,
    PIPELINE_KANBAN_CODES,
    PIPELINE_STAGE_LABELS_ES,
    PROSPECT_COMPANY,
    STAGE_LOST,
    STAGE_QUOTING,
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
    ensure_party_for_opportunity,
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
    update_opportunity,
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
    vista: str = Query(default="kanban"),
    q: str = Query(default=""),
    quick: str = Query(default=""),
    error: str = Query(default=""),
    ok: str = Query(default=""),
):
    org = resolve_org(session, request)
    _require_crm(session, request, manage=False)
    access = _ctx_access(session, request)
    show_lost = include_lost in {"1", "true", "yes", "on"}
    view_mode = "lista" if (vista or "").lower() in {"lista", "list"} else "kanban"
    query = (q or "").strip().lower()
    stages = list_stages(session, access, org.id)
    kanban_codes = [s.code for s in stages if s.is_kanban] or list(PIPELINE_KANBAN_CODES)
    lost_reasons = list_lost_reasons(session, access, org.id)
    opps = list_opportunities(session, access, org.id, include_lost=show_lost)
    by_stage: dict[str, list] = {c: [] for c in kanban_codes}
    lost_rows: list = []
    list_rows: list = []
    prospect_cache: dict[str, str] = {}
    prospect_contact: dict[str, dict] = {}
    for o in opps:
        subtitle = ""
        if o.prospect_id:
            if o.prospect_id not in prospect_cache:
                try:
                    p = get_prospect(session, access, org.id, o.prospect_id)
                    prospect_cache[o.prospect_id] = _prospect_label(p)
                    prospect_contact[o.prospect_id] = {
                        "email": p.email,
                        "phone": p.phone or p.mobile,
                    }
                except AccessDenied:
                    prospect_cache[o.prospect_id] = "—"
                    prospect_contact[o.prospect_id] = {}
            subtitle = prospect_cache[o.prospect_id]
        hay = f"{o.title} {subtitle}".lower()
        if query and query not in hay:
            continue
        card = {
            "id": o.id,
            "title": o.title,
            "subtitle": subtitle,
            "stage_code": o.stage_code,
            "premium": o.estimated_premium,
            "probability": o.probability,
            "label": f"{o.title} · {subtitle}" if subtitle else o.title,
            "initial": (subtitle or o.title or "?")[:1].upper(),
            "prev_code": None,
            "next_code": None,
            "email": prospect_contact.get(o.prospect_id or "", {}).get("email"),
            "phone": prospect_contact.get(o.prospect_id or "", {}).get("phone"),
        }
        if o.stage_code in kanban_codes:
            idx = kanban_codes.index(o.stage_code)
            if idx > 0:
                card["prev_code"] = kanban_codes[idx - 1]
            if idx < len(kanban_codes) - 1:
                card["next_code"] = kanban_codes[idx + 1]
        list_rows.append(card)
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
            "open_quick": quick.upper() == code,
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
            list_rows=list_rows,
            lost_rows=lost_rows if show_lost else [],
            show_lost=show_lost,
            view_mode=view_mode,
            q=q or "",
            stage_labels=PIPELINE_STAGE_LABELS_ES,
            kanban_codes=kanban_codes,
            lost_reasons=lost_reasons,
            error=error or None,
            ok=ok or None,
        ),
    )


@router.post("/crm/rapido")
def crm_quick_create(
    request: Request,
    stage_code: str = Form("NEW"),
    contact_name: str = Form(...),
    title: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    estimated_premium: str = Form(""),
    session: Session = Depends(get_session),
):
    """Odoo-style quick create: prospect + opportunity in one step."""
    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        name = (contact_name or "").strip()
        if not name:
            raise CrmError("contacto requerido")
        parts = name.split(None, 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else None
        em = (email or "").strip() or None
        ph = (phone or "").strip() or None
        if not em and not ph:
            raise CrmError("indicá correo o teléfono")
        prosp = create_prospect(
            session,
            access,
            organization_id=org.id,
            prospect_type="PERSON",
            first_name=first,
            last_name=last,
            email=em,
            phone=ph,
            actor_id=_actor(request),
        )
        opp = create_opportunity(
            session,
            access,
            organization_id=org.id,
            title=title,
            prospect_id=prosp.id,
            estimated_premium=_money(estimated_premium),
            stage_code=(stage_code or "NEW").upper(),
            actor_id=_actor(request),
        )
    except (CrmError, AccessDenied, ValueError) as exc:
        return _err_redirect("/crm", exc)
    return RedirectResponse(
        f"/crm/oportunidades/{opp.id}?ok={quote('Oportunidad creada')}",
        status_code=303,
    )


@router.post("/crm/oportunidades/{opp_id}/cotizar")
def crm_opp_cotizar(
    opp_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Ensure Party from prospect if needed, move to QUOTING, open cotizador prefilled."""
    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        opp = get_opportunity(session, access, org.id, opp_id)
        party = ensure_party_for_opportunity(
            session,
            access,
            organization_id=org.id,
            opportunity_id=opp_id,
            actor_id=_actor(request),
        )
        if opp.stage_code not in {STAGE_WON, STAGE_LOST, STAGE_QUOTING}:
            set_opportunity_stage(
                session,
                access,
                organization_id=org.id,
                opportunity_id=opp_id,
                stage_code=STAGE_QUOTING,
                actor_id=_actor(request),
            )
        note = opp.title
        if opp.product_interest:
            note = f"{opp.title} · {opp.product_interest}"
        params = {
            "party_id": party.id,
            "crm_opportunity_id": opp.id,
            "note": note,
        }
        if opp.line_of_business_id:
            params["line_id"] = opp.line_of_business_id
    except (CrmError, AccessDenied, ValueError) as exc:
        return _err_redirect(f"/crm/oportunidades/{opp_id}", exc)
    return RedirectResponse(f"/cotizador?{urlencode(params)}#nueva", status_code=303)


@router.get("/crm/actividades", response_class=HTMLResponse)
def crm_actividades(
    request: Request,
    session: Session = Depends(get_session),
    error: str = Query(default=""),
    ok: str = Query(default=""),
):
    from collections import defaultdict
    from datetime import date as date_cls
    from datetime import timezone

    org = resolve_org(session, request)
    _require_crm(session, request, manage=False)
    access = _ctx_access(session, request)
    rows = list_activities(session, access, org.id)
    today = date_cls.today()
    groups: dict[str, list] = defaultdict(list)
    for a in rows:
        if a.due_at is None:
            key = "Sin fecha"
        else:
            d = a.due_at.astimezone(timezone.utc).date() if a.due_at.tzinfo else a.due_at.date()
            if d < today and a.status in {"PENDING", "OVERDUE"}:
                key = f"Vencidas · {d.isoformat()}"
            elif d == today:
                key = f"Hoy · {d.isoformat()}"
            else:
                key = d.isoformat()
        groups[key].append(a)

    def _sort_key(k: str):
        if k.startswith("Vencidas"):
            return (0, k)
        if k.startswith("Hoy"):
            return (1, k)
        if k == "Sin fecha":
            return (3, k)
        return (2, k)

    grouped = [(k, groups[k]) for k in sorted(groups.keys(), key=_sort_key)]
    return templates.TemplateResponse(
        request,
        "crm_actividades.html",
        _ctx(
            request,
            "crm_actividades",
            org_name=org.name,
            grouped=grouped,
            activity_types=sorted(ACTIVITY_TYPES),
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
            activity_count=len(activities),
            pending_activities=sum(1 for a in activities if a.status in {"PENDING", "OVERDUE"}),
            stage_labels=PIPELINE_STAGE_LABELS_ES,
            activity_types=sorted(ACTIVITY_TYPES),
            kanban_codes=[s.code for s in stages if s.is_kanban] or list(PIPELINE_KANBAN_CODES),
            error=error or None,
            ok=ok or None,
        ),
    )


@router.post("/crm/oportunidades/{opp_id}/editar")
def crm_opp_editar(
    opp_id: str,
    request: Request,
    title: str = Form(...),
    estimated_premium: str = Form(""),
    probability: str = Form(""),
    expected_close_date: str = Form(""),
    product_interest: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    from datetime import date as date_cls

    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        prob = None
        if (probability or "").strip() != "":
            prob = int(float(probability))
        close = None
        clear_close = False
        if (expected_close_date or "").strip() == "":
            clear_close = True
        else:
            close = date_cls.fromisoformat(expected_close_date)
        prem_raw = (estimated_premium or "").strip()
        update_opportunity(
            session,
            access,
            organization_id=org.id,
            opportunity_id=opp_id,
            title=title,
            estimated_premium=_money(prem_raw) if prem_raw else None,
            clear_premium=not prem_raw,
            probability=prob,
            expected_close_date=close,
            clear_close_date=clear_close,
            product_interest=product_interest,
            notes=notes,
            actor_id=_actor(request),
        )
    except (CrmError, AccessDenied, ValueError) as exc:
        return _err_redirect(f"/crm/oportunidades/{opp_id}", exc)
    return RedirectResponse(
        f"/crm/oportunidades/{opp_id}?ok={quote('Guardado')}",
        status_code=303,
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
    due_at: str = Form(""),
    session: Session = Depends(get_session),
):
    from datetime import datetime

    org = resolve_org(session, request)
    _require_crm(session, request, manage=True)
    access = _ctx_access(session, request)
    try:
        due = None
        if (due_at or "").strip():
            raw = due_at.strip()
            due = datetime.fromisoformat(raw if "T" in raw else f"{raw}T09:00:00")
        create_activity(
            session,
            access,
            organization_id=org.id,
            opportunity_id=opp_id,
            activity_type=activity_type,
            title=title or None,
            notes=notes or None,
            due_at=due,
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
