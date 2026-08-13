"""ADR-011 F3 — CRM REST API `/api/crm/v1` (DEV)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from corredores.services.access_control import AccessDenied
from corredores.services.crm_service import (
    CrmAmbiguousCustomer,
    CrmError,
    activity_dict,
    assign_opportunity,
    assign_prospect,
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
    opportunity_dict,
    prospect_dict,
    reopen_opportunity,
    set_opportunity_stage,
)
from corredores.web.auth_session import read_session
from corredores.web.deps import current_access_context, get_session, resolve_org

router = APIRouter(prefix="/api/crm/v1", tags=["crm-v1"])


def _actor(request: Request) -> str | None:
    p = read_session(request)
    return p.actor_id if p else None


def _ctx(session: Session, request: Request):
    return current_access_context(session, request)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, AccessDenied):
        if exc.not_found:
            return HTTPException(404, "not found")
        return HTTPException(403, str(exc) or "forbidden")
    if isinstance(exc, CrmAmbiguousCustomer):
        return HTTPException(
            409,
            {
                "detail": "ambiguous_customer",
                "matches": [
                    {
                        "id": p.id,
                        "first_name": p.first_name,
                        "last_name": p.last_name,
                        "legal_name": p.legal_name,
                        "email": p.email,
                        "phone": p.phone,
                        "national_id": p.national_id,
                    }
                    for p in exc.matches
                ],
            },
        )
    if isinstance(exc, CrmError):
        return HTTPException(400, str(exc))
    raise exc


# --- Schemas ---


class ProspectIn(BaseModel):
    prospect_type: str = "PERSON"
    first_name: str | None = None
    last_name: str | None = None
    company_name: str | None = None
    identification_type: str | None = None
    identification_number: str | None = None
    phone: str | None = None
    mobile: str | None = None
    email: str | None = None
    source_id: str | None = None
    referral_source_id: str | None = None
    assigned_producer_id: str | None = None
    assigned_executive_id: str | None = None
    office_id: str | None = None
    notes: str | None = None


class AssignIn(BaseModel):
    assigned_producer_id: str | None = None
    assigned_executive_id: str | None = None


class OpportunityIn(BaseModel):
    title: str
    prospect_id: str | None = None
    customer_id: str | None = None
    line_of_business_id: str | None = None
    product_interest: str | None = None
    carrier_id: str | None = None
    assigned_producer_id: str | None = None
    assigned_executive_id: str | None = None
    office_id: str | None = None
    estimated_premium: Decimal | None = None
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    source_id: str | None = None
    referral_source_id: str | None = None
    notes: str | None = None
    stage_code: str = "NEW"


class StageIn(BaseModel):
    stage_code: str
    lost_reason_id: str | None = None


class LostIn(BaseModel):
    lost_reason_id: str


class ReopenIn(BaseModel):
    stage_code: str = "NEGOTIATION"


class ConvertIn(BaseModel):
    customer_id: str | None = None


class ActivityIn(BaseModel):
    activity_type: str = "FOLLOW_UP"
    title: str | None = None
    opportunity_id: str | None = None
    prospect_id: str | None = None
    due_at: datetime | None = None
    assignee_subject_id: str | None = None
    notes: str | None = None


class ActivityCompleteIn(BaseModel):
    result: str | None = None


# --- Catalog ---


@router.get("/stages")
def api_stages(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session, request)
    try:
        rows = list_stages(session, _ctx(session, request), org.id)
        return {
            "items": [
                {
                    "id": r.id,
                    "code": r.code,
                    "name": r.name,
                    "sequence": r.sequence,
                    "is_won": r.is_won,
                    "is_lost": r.is_lost,
                    "is_kanban": r.is_kanban,
                }
                for r in rows
            ]
        }
    except Exception as e:
        raise _http(e) from e


@router.get("/lead-sources")
def api_lead_sources(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session, request)
    try:
        rows = list_lead_sources(session, _ctx(session, request), org.id)
        return {"items": [{"id": r.id, "code": r.code, "name": r.name} for r in rows]}
    except Exception as e:
        raise _http(e) from e


@router.get("/lost-reasons")
def api_lost_reasons(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session, request)
    try:
        rows = list_lost_reasons(session, _ctx(session, request), org.id)
        return {"items": [{"id": r.id, "code": r.code, "name": r.name} for r in rows]}
    except Exception as e:
        raise _http(e) from e


# --- Prospects ---


@router.get("/prospects")
def api_prospects_list(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session, request)
    try:
        rows = list_prospects(session, _ctx(session, request), org.id)
        return {"items": [prospect_dict(r) for r in rows]}
    except Exception as e:
        raise _http(e) from e


@router.post("/prospects", status_code=201)
def api_prospects_create(
    body: ProspectIn, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    try:
        row = create_prospect(
            session,
            _ctx(session, request),
            organization_id=org.id,
            actor_id=_actor(request),
            **body.model_dump(),
        )
        return prospect_dict(row)
    except Exception as e:
        raise _http(e) from e


@router.get("/prospects/{prospect_id}")
def api_prospects_get(
    prospect_id: str, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    try:
        row = get_prospect(session, _ctx(session, request), org.id, prospect_id)
        return prospect_dict(row)
    except Exception as e:
        raise _http(e) from e


@router.post("/prospects/{prospect_id}/assign")
def api_prospects_assign(
    prospect_id: str,
    body: AssignIn,
    request: Request,
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    try:
        row = assign_prospect(
            session,
            _ctx(session, request),
            organization_id=org.id,
            prospect_id=prospect_id,
            assigned_producer_id=body.assigned_producer_id,
            assigned_executive_id=body.assigned_executive_id,
            actor_id=_actor(request),
        )
        return prospect_dict(row)
    except Exception as e:
        raise _http(e) from e


# --- Opportunities ---


@router.get("/opportunities")
def api_opportunities_list(
    request: Request,
    stage_code: str | None = Query(default=None),
    include_lost: bool = Query(default=True),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    try:
        rows = list_opportunities(
            session,
            _ctx(session, request),
            org.id,
            stage_code=stage_code,
            include_lost=include_lost,
        )
        return {"items": [opportunity_dict(r) for r in rows]}
    except Exception as e:
        raise _http(e) from e


@router.post("/opportunities", status_code=201)
def api_opportunities_create(
    body: OpportunityIn, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    try:
        row = create_opportunity(
            session,
            _ctx(session, request),
            organization_id=org.id,
            actor_id=_actor(request),
            **body.model_dump(),
        )
        return opportunity_dict(row)
    except Exception as e:
        raise _http(e) from e


@router.get("/opportunities/{opportunity_id}")
def api_opportunities_get(
    opportunity_id: str, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    try:
        row = get_opportunity(session, _ctx(session, request), org.id, opportunity_id)
        return opportunity_dict(row)
    except Exception as e:
        raise _http(e) from e


@router.post("/opportunities/{opportunity_id}/stage")
def api_opportunities_stage(
    opportunity_id: str,
    body: StageIn,
    request: Request,
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    try:
        row = set_opportunity_stage(
            session,
            _ctx(session, request),
            organization_id=org.id,
            opportunity_id=opportunity_id,
            stage_code=body.stage_code,
            lost_reason_id=body.lost_reason_id,
            actor_id=_actor(request),
        )
        return opportunity_dict(row)
    except Exception as e:
        raise _http(e) from e


@router.post("/opportunities/{opportunity_id}/won")
def api_opportunities_won(
    opportunity_id: str, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    try:
        row = mark_won(
            session,
            _ctx(session, request),
            organization_id=org.id,
            opportunity_id=opportunity_id,
            actor_id=_actor(request),
        )
        return opportunity_dict(row)
    except Exception as e:
        raise _http(e) from e


@router.post("/opportunities/{opportunity_id}/lost")
def api_opportunities_lost(
    opportunity_id: str,
    body: LostIn,
    request: Request,
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    try:
        row = mark_lost(
            session,
            _ctx(session, request),
            organization_id=org.id,
            opportunity_id=opportunity_id,
            lost_reason_id=body.lost_reason_id,
            actor_id=_actor(request),
        )
        return opportunity_dict(row)
    except Exception as e:
        raise _http(e) from e


@router.post("/opportunities/{opportunity_id}/reopen")
def api_opportunities_reopen(
    opportunity_id: str,
    body: ReopenIn,
    request: Request,
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    try:
        row = reopen_opportunity(
            session,
            _ctx(session, request),
            organization_id=org.id,
            opportunity_id=opportunity_id,
            stage_code=body.stage_code,
            actor_id=_actor(request),
        )
        return opportunity_dict(row)
    except Exception as e:
        raise _http(e) from e


@router.post("/opportunities/{opportunity_id}/assign")
def api_opportunities_assign(
    opportunity_id: str,
    body: AssignIn,
    request: Request,
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    try:
        row = assign_opportunity(
            session,
            _ctx(session, request),
            organization_id=org.id,
            opportunity_id=opportunity_id,
            assigned_producer_id=body.assigned_producer_id,
            assigned_executive_id=body.assigned_executive_id,
            actor_id=_actor(request),
        )
        return opportunity_dict(row)
    except Exception as e:
        raise _http(e) from e


@router.post("/opportunities/{opportunity_id}/convert")
def api_opportunities_convert(
    opportunity_id: str,
    body: ConvertIn,
    request: Request,
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    try:
        opp, party, action = convert_opportunity_to_customer(
            session,
            _ctx(session, request),
            organization_id=org.id,
            opportunity_id=opportunity_id,
            customer_id=body.customer_id,
            actor_id=_actor(request),
        )
        return {
            "opportunity": opportunity_dict(opp),
            "customer_id": party.id,
            "action": action,
        }
    except Exception as e:
        raise _http(e) from e


# --- Activities ---


@router.get("/activities")
def api_activities_list(
    request: Request,
    opportunity_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    try:
        rows = list_activities(
            session,
            _ctx(session, request),
            org.id,
            opportunity_id=opportunity_id,
            status=status,
        )
        return {"items": [activity_dict(r) for r in rows]}
    except Exception as e:
        raise _http(e) from e


@router.post("/activities", status_code=201)
def api_activities_create(
    body: ActivityIn, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    try:
        row = create_activity(
            session,
            _ctx(session, request),
            organization_id=org.id,
            actor_id=_actor(request),
            **body.model_dump(),
        )
        return activity_dict(row)
    except Exception as e:
        raise _http(e) from e


@router.post("/activities/{activity_id}/complete")
def api_activities_complete(
    activity_id: str,
    body: ActivityCompleteIn,
    request: Request,
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    try:
        row = complete_activity(
            session,
            _ctx(session, request),
            organization_id=org.id,
            activity_id=activity_id,
            result=body.result,
            actor_id=_actor(request),
        )
        return activity_dict(row)
    except Exception as e:
        raise _http(e) from e
