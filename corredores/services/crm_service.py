"""ADR-011 F3 — CRM application service (prospects, opportunities, activities).

Uses crm_access for RBAC. AuditEvent for mutations. No UI.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from corredores.domain.crm_constants import (
    ACTIVITY_DONE,
    ACTIVITY_PENDING,
    ACTIVITY_TYPES,
    PROSPECT_COMPANY,
    PROSPECT_CONVERTED,
    PROSPECT_OPEN,
    PROSPECT_PERSON,
    PROSPECT_TYPES,
    STAGE_LOST,
    STAGE_NEW,
    STAGE_WON,
)
from corredores.domain.enums import DataSource, PartyRoleType, PartyType
from corredores.domain.models import (
    AuditEvent,
    CrmActivity,
    CrmLeadSource,
    CrmLostReason,
    CrmOpportunity,
    CrmPipelineStage,
    CrmProspect,
    Party,
    PartyRole,
)
from corredores.services.access_control import AccessContext, AccessDenied
from corredores.services.crm_access import (
    PERM_CRM_READ,
    apply_scope_to_activity_query,
    apply_scope_to_opportunity_query,
    apply_scope_to_prospect_query,
    require_activity_in_scope,
    require_crm_manage,
    require_opportunity_in_scope,
    require_prospect_in_scope,
)
from corredores.services.crm_catalog_seed import ensure_default_crm_catalogs


class CrmError(Exception):
    """Domain/validation error for CRM (map to 400)."""


class CrmAmbiguousCustomer(CrmError):
    """Multiple Customer matches — caller must resolve (ADR-011 §17)."""

    def __init__(self, matches: list[Party]):
        self.matches = matches
        super().__init__(f"ambiguous customer matches: {len(matches)}")


def _audit(
    session: Session,
    *,
    organization_id: str,
    actor_id: str | None,
    entity_type: str,
    entity_id: str,
    action: str,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            detail_json=json.dumps(detail or {}),
        )
    )


def _require_read(ctx: AccessContext | None) -> None:
    if ctx is not None:
        from corredores.services.access_control import require_permission

        require_permission(ctx, PERM_CRM_READ)


def _require_manage(ctx: AccessContext | None) -> None:
    if ctx is not None:
        require_crm_manage(ctx)


def _norm(s: str | None) -> str | None:
    v = (s or "").strip()
    return v or None


def _validate_prospect_contact(
    *,
    prospect_type: str,
    first_name: str | None,
    last_name: str | None,
    company_name: str | None,
    phone: str | None,
    mobile: str | None,
    email: str | None,
) -> None:
    if prospect_type not in PROSPECT_TYPES:
        raise CrmError("prospect_type inválido")
    if prospect_type == PROSPECT_PERSON:
        if not (first_name or last_name):
            raise CrmError("nombre requerido para persona")
    else:
        if not company_name:
            raise CrmError("company_name requerido para empresa")
    if not (phone or mobile or email):
        raise CrmError("se requiere al menos un medio de contacto (phone, mobile o email)")


def _stage_for_code(
    session: Session, organization_id: str, code: str
) -> CrmPipelineStage:
    ensure_default_crm_catalogs(session, organization_id)
    row = (
        session.query(CrmPipelineStage)
        .filter_by(organization_id=organization_id, code=code, active=True)
        .one_or_none()
    )
    if row is None:
        raise CrmError(f"etapa desconocida: {code}")
    return row


# --- Catalogs ---


def list_stages(session: Session, ctx: AccessContext | None, organization_id: str) -> list[CrmPipelineStage]:
    _require_read(ctx)
    ensure_default_crm_catalogs(session, organization_id)
    return (
        session.query(CrmPipelineStage)
        .filter_by(organization_id=organization_id, active=True)
        .order_by(CrmPipelineStage.sequence.asc())
        .all()
    )


def list_lead_sources(session: Session, ctx: AccessContext | None, organization_id: str) -> list[CrmLeadSource]:
    _require_read(ctx)
    ensure_default_crm_catalogs(session, organization_id)
    return (
        session.query(CrmLeadSource)
        .filter_by(organization_id=organization_id, active=True)
        .order_by(CrmLeadSource.sort_order.asc())
        .all()
    )


def list_lost_reasons(session: Session, ctx: AccessContext | None, organization_id: str) -> list[CrmLostReason]:
    _require_read(ctx)
    ensure_default_crm_catalogs(session, organization_id)
    return (
        session.query(CrmLostReason)
        .filter_by(organization_id=organization_id, active=True)
        .order_by(CrmLostReason.sort_order.asc())
        .all()
    )


# --- Prospects ---


def list_prospects(
    session: Session, ctx: AccessContext | None, organization_id: str
) -> list[CrmProspect]:
    _require_read(ctx)
    q = session.query(CrmProspect).filter_by(organization_id=organization_id)
    if ctx is not None:
        q = apply_scope_to_prospect_query(q, session, ctx)
    return q.order_by(CrmProspect.created_at.desc()).all()


def get_prospect(
    session: Session, ctx: AccessContext | None, organization_id: str, prospect_id: str
) -> CrmProspect:
    if ctx is not None:
        row = require_prospect_in_scope(session, ctx, prospect_id)
    else:
        row = session.get(CrmProspect, prospect_id)
        if row is None or row.organization_id != organization_id:
            raise AccessDenied("not found", not_found=True)
    return row


def create_prospect(
    session: Session,
    ctx: AccessContext | None,
    *,
    organization_id: str,
    prospect_type: str = PROSPECT_PERSON,
    first_name: str | None = None,
    last_name: str | None = None,
    company_name: str | None = None,
    identification_type: str | None = None,
    identification_number: str | None = None,
    phone: str | None = None,
    mobile: str | None = None,
    email: str | None = None,
    source_id: str | None = None,
    referral_source_id: str | None = None,
    assigned_producer_id: str | None = None,
    assigned_executive_id: str | None = None,
    office_id: str | None = None,
    notes: str | None = None,
    actor_id: str | None = None,
) -> CrmProspect:
    _require_manage(ctx)
    pt = (prospect_type or PROSPECT_PERSON).upper()
    fn, ln, cn = _norm(first_name), _norm(last_name), _norm(company_name)
    ph, mb, em = _norm(phone), _norm(mobile), _norm(email)
    _validate_prospect_contact(
        prospect_type=pt,
        first_name=fn,
        last_name=ln,
        company_name=cn,
        phone=ph,
        mobile=mb,
        email=em,
    )
    # PRODUCER defaults assignment to self
    if ctx and ctx.producer_profile_id and not assigned_producer_id:
        assigned_producer_id = ctx.producer_profile_id
    row = CrmProspect(
        organization_id=organization_id,
        prospect_type=pt,
        first_name=fn,
        last_name=ln,
        company_name=cn,
        identification_type=_norm(identification_type),
        identification_number=_norm(identification_number),
        phone=ph,
        mobile=mb,
        email=em.lower() if em else None,
        source_id=source_id or None,
        referral_source_id=referral_source_id or None,
        assigned_producer_id=assigned_producer_id or None,
        assigned_executive_id=_norm(assigned_executive_id),
        office_id=_norm(office_id),
        status=PROSPECT_OPEN,
        notes=_norm(notes),
        created_by=actor_id,
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CrmProspect",
        entity_id=row.id,
        action="CRM_PROSPECT_CREATED",
        detail={"type": pt},
    )
    session.flush()
    return row


def assign_prospect(
    session: Session,
    ctx: AccessContext | None,
    *,
    organization_id: str,
    prospect_id: str,
    assigned_producer_id: str | None = None,
    assigned_executive_id: str | None = None,
    actor_id: str | None = None,
) -> CrmProspect:
    _require_manage(ctx)
    row = get_prospect(session, ctx, organization_id, prospect_id)
    before = {
        "producer": row.assigned_producer_id,
        "executive": row.assigned_executive_id,
    }
    if assigned_producer_id is not None:
        row.assigned_producer_id = assigned_producer_id or None
    if assigned_executive_id is not None:
        row.assigned_executive_id = _norm(assigned_executive_id)
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CrmProspect",
        entity_id=row.id,
        action="CRM_PROSPECT_ASSIGNED",
        detail={"before": before, "after": {
            "producer": row.assigned_producer_id,
            "executive": row.assigned_executive_id,
        }},
    )
    session.flush()
    return row


# --- Opportunities ---


def list_opportunities(
    session: Session,
    ctx: AccessContext | None,
    organization_id: str,
    *,
    stage_code: str | None = None,
    include_lost: bool = True,
) -> list[CrmOpportunity]:
    _require_read(ctx)
    q = session.query(CrmOpportunity).filter_by(organization_id=organization_id)
    if ctx is not None:
        q = apply_scope_to_opportunity_query(q, session, ctx)
    if stage_code:
        q = q.filter(CrmOpportunity.stage_code == stage_code.upper())
    if not include_lost:
        q = q.filter(CrmOpportunity.stage_code != STAGE_LOST)
    return q.order_by(CrmOpportunity.updated_at.desc()).all()


def get_opportunity(
    session: Session, ctx: AccessContext | None, organization_id: str, opportunity_id: str
) -> CrmOpportunity:
    if ctx is not None:
        return require_opportunity_in_scope(session, ctx, opportunity_id)
    row = session.get(CrmOpportunity, opportunity_id)
    if row is None or row.organization_id != organization_id:
        raise AccessDenied("not found", not_found=True)
    return row


def create_opportunity(
    session: Session,
    ctx: AccessContext | None,
    *,
    organization_id: str,
    title: str,
    prospect_id: str | None = None,
    customer_id: str | None = None,
    line_of_business_id: str | None = None,
    product_interest: str | None = None,
    carrier_id: str | None = None,
    assigned_producer_id: str | None = None,
    assigned_executive_id: str | None = None,
    office_id: str | None = None,
    estimated_premium: Decimal | str | None = None,
    probability: int | None = None,
    expected_close_date: date | None = None,
    source_id: str | None = None,
    referral_source_id: str | None = None,
    notes: str | None = None,
    stage_code: str = STAGE_NEW,
    actor_id: str | None = None,
) -> CrmOpportunity:
    _require_manage(ctx)
    title_n = _norm(title)
    if not title_n:
        raise CrmError("title requerido")
    if not prospect_id and not customer_id:
        raise CrmError("prospect_id o customer_id requerido")
    if prospect_id:
        get_prospect(session, ctx, organization_id, prospect_id)
    if customer_id:
        party = session.get(Party, customer_id)
        if party is None or party.organization_id != organization_id:
            raise CrmError("customer_id inválido")
    if ctx and ctx.producer_profile_id and not assigned_producer_id:
        assigned_producer_id = ctx.producer_profile_id
        if prospect_id:
            prosp = session.get(CrmProspect, prospect_id)
            if prosp and not prosp.assigned_producer_id:
                prosp.assigned_producer_id = assigned_producer_id
    code = (stage_code or STAGE_NEW).upper()
    stage = _stage_for_code(session, organization_id, code)
    prem = None
    if estimated_premium is not None and str(estimated_premium) != "":
        prem = Decimal(str(estimated_premium)).quantize(Decimal("0.01"))
    row = CrmOpportunity(
        organization_id=organization_id,
        prospect_id=prospect_id,
        customer_id=customer_id,
        title=title_n,
        line_of_business_id=line_of_business_id,
        product_interest=_norm(product_interest),
        carrier_id=carrier_id,
        assigned_producer_id=assigned_producer_id,
        assigned_executive_id=_norm(assigned_executive_id),
        office_id=_norm(office_id),
        stage_id=stage.id,
        stage_code=stage.code,
        estimated_premium=prem,
        probability=probability,
        expected_close_date=expected_close_date,
        source_id=source_id,
        referral_source_id=referral_source_id,
        notes=_norm(notes),
        created_by=actor_id,
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CrmOpportunity",
        entity_id=row.id,
        action="CRM_OPPORTUNITY_CREATED",
        detail={"stage": stage.code, "title": title_n},
    )
    session.flush()
    return row


def set_opportunity_stage(
    session: Session,
    ctx: AccessContext | None,
    *,
    organization_id: str,
    opportunity_id: str,
    stage_code: str,
    lost_reason_id: str | None = None,
    actor_id: str | None = None,
) -> CrmOpportunity:
    _require_manage(ctx)
    row = get_opportunity(session, ctx, organization_id, opportunity_id)
    code = stage_code.upper()
    stage = _stage_for_code(session, organization_id, code)
    before = row.stage_code
    now = datetime.now(timezone.utc)
    row.stage_id = stage.id
    row.stage_code = stage.code
    if stage.is_won or code == STAGE_WON:
        row.won_at = now
        row.lost_at = None
        row.lost_reason_id = None
    elif stage.is_lost or code == STAGE_LOST:
        if not lost_reason_id:
            raise CrmError("lost_reason_id requerido al marcar LOST")
        reason = session.get(CrmLostReason, lost_reason_id)
        if reason is None or reason.organization_id != organization_id:
            raise CrmError("lost_reason_id inválido")
        row.lost_at = now
        row.lost_reason_id = lost_reason_id
        row.won_at = None
    else:
        # reopen path clears terminal stamps when leaving LOST/WON
        if before == STAGE_LOST and code != STAGE_LOST:
            row.reopened_at = now
            row.lost_at = None
            row.lost_reason_id = None
        if before == STAGE_WON and code != STAGE_WON:
            row.won_at = None
    action = "CRM_OPPORTUNITY_STAGE_CHANGED"
    if code == STAGE_WON:
        action = "CRM_OPPORTUNITY_WON"
    elif code == STAGE_LOST:
        action = "CRM_OPPORTUNITY_LOST"
    elif before == STAGE_LOST:
        action = "CRM_OPPORTUNITY_REOPENED"
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CrmOpportunity",
        entity_id=row.id,
        action=action,
        detail={"from": before, "to": code, "lost_reason_id": lost_reason_id},
    )
    session.flush()
    return row


def mark_won(
    session: Session,
    ctx: AccessContext | None,
    *,
    organization_id: str,
    opportunity_id: str,
    actor_id: str | None = None,
) -> CrmOpportunity:
    return set_opportunity_stage(
        session,
        ctx,
        organization_id=organization_id,
        opportunity_id=opportunity_id,
        stage_code=STAGE_WON,
        actor_id=actor_id,
    )


def mark_lost(
    session: Session,
    ctx: AccessContext | None,
    *,
    organization_id: str,
    opportunity_id: str,
    lost_reason_id: str,
    actor_id: str | None = None,
) -> CrmOpportunity:
    return set_opportunity_stage(
        session,
        ctx,
        organization_id=organization_id,
        opportunity_id=opportunity_id,
        stage_code=STAGE_LOST,
        lost_reason_id=lost_reason_id,
        actor_id=actor_id,
    )


def reopen_opportunity(
    session: Session,
    ctx: AccessContext | None,
    *,
    organization_id: str,
    opportunity_id: str,
    stage_code: str = "NEGOTIATION",
    actor_id: str | None = None,
) -> CrmOpportunity:
    return set_opportunity_stage(
        session,
        ctx,
        organization_id=organization_id,
        opportunity_id=opportunity_id,
        stage_code=stage_code or "NEGOTIATION",
        actor_id=actor_id,
    )


def assign_opportunity(
    session: Session,
    ctx: AccessContext | None,
    *,
    organization_id: str,
    opportunity_id: str,
    assigned_producer_id: str | None = None,
    assigned_executive_id: str | None = None,
    actor_id: str | None = None,
) -> CrmOpportunity:
    _require_manage(ctx)
    row = get_opportunity(session, ctx, organization_id, opportunity_id)
    before = {
        "producer": row.assigned_producer_id,
        "executive": row.assigned_executive_id,
    }
    if assigned_producer_id is not None:
        row.assigned_producer_id = assigned_producer_id or None
    if assigned_executive_id is not None:
        row.assigned_executive_id = _norm(assigned_executive_id)
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CrmOpportunity",
        entity_id=row.id,
        action="CRM_OPPORTUNITY_ASSIGNED",
        detail={"before": before, "after": {
            "producer": row.assigned_producer_id,
            "executive": row.assigned_executive_id,
        }},
    )
    session.flush()
    return row


# --- Activities ---


def list_activities(
    session: Session,
    ctx: AccessContext | None,
    organization_id: str,
    *,
    opportunity_id: str | None = None,
    status: str | None = None,
) -> list[CrmActivity]:
    _require_read(ctx)
    q = session.query(CrmActivity).filter_by(organization_id=organization_id)
    if ctx is not None:
        q = apply_scope_to_activity_query(q, session, ctx)
    if opportunity_id:
        q = q.filter(CrmActivity.opportunity_id == opportunity_id)
    if status:
        q = q.filter(CrmActivity.status == status.upper())
    return q.order_by(CrmActivity.due_at.asc().nullslast(), CrmActivity.created_at.desc()).all()


def create_activity(
    session: Session,
    ctx: AccessContext | None,
    *,
    organization_id: str,
    activity_type: str = "FOLLOW_UP",
    title: str | None = None,
    opportunity_id: str | None = None,
    prospect_id: str | None = None,
    due_at: datetime | None = None,
    assignee_subject_id: str | None = None,
    notes: str | None = None,
    actor_id: str | None = None,
) -> CrmActivity:
    _require_manage(ctx)
    at = (activity_type or "FOLLOW_UP").upper()
    if at not in ACTIVITY_TYPES:
        raise CrmError("activity_type inválido")
    if opportunity_id:
        get_opportunity(session, ctx, organization_id, opportunity_id)
    if prospect_id:
        get_prospect(session, ctx, organization_id, prospect_id)
    if not opportunity_id and not prospect_id:
        raise CrmError("opportunity_id o prospect_id requerido")
    row = CrmActivity(
        organization_id=organization_id,
        opportunity_id=opportunity_id,
        prospect_id=prospect_id,
        activity_type=at,
        title=_norm(title),
        due_at=due_at,
        status=ACTIVITY_PENDING,
        notes=_norm(notes),
        assignee_subject_id=_norm(assignee_subject_id) or (ctx.subject_id if ctx else actor_id),
        created_by=actor_id,
    )
    session.add(row)
    session.flush()
    if opportunity_id and due_at:
        opp = session.get(CrmOpportunity, opportunity_id)
        if opp and (opp.next_activity_at is None or due_at < opp.next_activity_at):
            opp.next_activity_at = due_at
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CrmActivity",
        entity_id=row.id,
        action="CRM_ACTIVITY_CREATED",
        detail={"type": at},
    )
    session.flush()
    return row


def complete_activity(
    session: Session,
    ctx: AccessContext | None,
    *,
    organization_id: str,
    activity_id: str,
    result: str | None = None,
    actor_id: str | None = None,
) -> CrmActivity:
    _require_manage(ctx)
    if ctx is not None:
        row = require_activity_in_scope(session, ctx, activity_id)
    else:
        row = session.get(CrmActivity, activity_id)
        if row is None or row.organization_id != organization_id:
            raise AccessDenied("not found", not_found=True)
    row.status = ACTIVITY_DONE
    row.result = _norm(result)
    row.completed_at = datetime.now(timezone.utc)
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CrmActivity",
        entity_id=row.id,
        action="CRM_ACTIVITY_DONE",
        detail={"result": row.result},
    )
    session.flush()
    return row


# --- Conversion ---


def find_customer_matches(
    session: Session,
    *,
    organization_id: str,
    identification_number: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    mobile: str | None = None,
) -> list[Party]:
    """Non-destructive match candidates within org (ADR-011 §17)."""
    clauses = []
    idn = _norm(identification_number)
    em = _norm(email)
    ph = _norm(phone)
    mb = _norm(mobile)
    if idn:
        clauses.append(func.lower(Party.national_id) == idn.lower())
    if em:
        clauses.append(func.lower(Party.email) == em.lower())
    phones = [p for p in (ph, mb) if p]
    for p in phones:
        clauses.append(Party.phone == p)
    if not clauses:
        return []
    rows = (
        session.query(Party)
        .filter(Party.organization_id == organization_id)
        .filter(or_(*clauses))
        .all()
    )
    # Prefer parties that already have CLIENT role
    out: list[Party] = []
    for p in rows:
        role = (
            session.query(PartyRole)
            .filter_by(
                organization_id=organization_id,
                party_id=p.id,
                role_type=PartyRoleType.CLIENT,
            )
            .first()
        )
        if role is not None:
            out.append(p)
    return out or rows


def convert_opportunity_to_customer(
    session: Session,
    ctx: AccessContext | None,
    *,
    organization_id: str,
    opportunity_id: str,
    customer_id: str | None = None,
    actor_id: str | None = None,
) -> tuple[CrmOpportunity, Party, str]:
    """WON → create/link Customer. Returns (opp, party, action LINK|CREATE).

    Raises CrmAmbiguousCustomer if multiple matches and customer_id not provided.
    """
    _require_manage(ctx)
    opp = get_opportunity(session, ctx, organization_id, opportunity_id)
    if opp.stage_code != STAGE_WON:
        raise CrmError("la oportunidad debe estar WON para convertir")

    action = "LINK"
    party: Party | None = None

    if customer_id:
        party = session.get(Party, customer_id)
        if party is None or party.organization_id != organization_id:
            raise CrmError("customer_id inválido")
    elif opp.customer_id:
        party = session.get(Party, opp.customer_id)
    elif opp.prospect_id:
        prosp = session.get(CrmProspect, opp.prospect_id)
        if prosp and prosp.converted_customer_id:
            party = session.get(Party, prosp.converted_customer_id)
        elif prosp:
            matches = find_customer_matches(
                session,
                organization_id=organization_id,
                identification_number=prosp.identification_number,
                email=prosp.email,
                phone=prosp.phone,
                mobile=prosp.mobile,
            )
            if len(matches) > 1:
                raise CrmAmbiguousCustomer(matches)
            if len(matches) == 1:
                party = matches[0]
            else:
                # CREATE from prospect
                action = "CREATE"
                if prosp.prospect_type == PROSPECT_COMPANY:
                    party = Party(
                        organization_id=organization_id,
                        party_type=PartyType.ORGANIZATION,
                        legal_name=prosp.company_name,
                        national_id=prosp.identification_number,
                        phone=prosp.phone or prosp.mobile,
                        email=prosp.email,
                        data_source=DataSource.MANUAL,
                    )
                else:
                    party = Party(
                        organization_id=organization_id,
                        party_type=PartyType.PERSON,
                        first_name=prosp.first_name,
                        last_name=prosp.last_name,
                        national_id=prosp.identification_number,
                        phone=prosp.phone or prosp.mobile,
                        email=prosp.email,
                        data_source=DataSource.MANUAL,
                    )
                session.add(party)
                session.flush()

    if party is None:
        raise CrmError("no hay datos suficientes para crear/vincular Customer")

    # Ensure CLIENT role
    role = (
        session.query(PartyRole)
        .filter_by(
            organization_id=organization_id,
            party_id=party.id,
            role_type=PartyRoleType.CLIENT,
            context_type="GLOBAL",
        )
        .first()
    )
    if role is None:
        session.add(
            PartyRole(
                organization_id=organization_id,
                party_id=party.id,
                role_type=PartyRoleType.CLIENT,
                context_type="GLOBAL",
                context_id=None,
            )
        )

    opp.customer_id = party.id
    if opp.prospect_id:
        prosp = session.get(CrmProspect, opp.prospect_id)
        if prosp:
            prosp.converted_customer_id = party.id
            prosp.status = PROSPECT_CONVERTED

    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CrmOpportunity",
        entity_id=opp.id,
        action="CRM_CONVERTED_TO_CUSTOMER",
        detail={"customer_id": party.id, "action": action},
    )
    session.flush()
    return opp, party, action


# --- Serialization helpers ---


def prospect_dict(row: CrmProspect) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "prospect_type": row.prospect_type,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "company_name": row.company_name,
        "identification_type": row.identification_type,
        "identification_number": row.identification_number,
        "phone": row.phone,
        "mobile": row.mobile,
        "email": row.email,
        "source_id": row.source_id,
        "referral_source_id": row.referral_source_id,
        "assigned_producer_id": row.assigned_producer_id,
        "assigned_executive_id": row.assigned_executive_id,
        "office_id": row.office_id,
        "status": row.status,
        "notes": row.notes,
        "converted_customer_id": row.converted_customer_id,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def opportunity_dict(row: CrmOpportunity) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "prospect_id": row.prospect_id,
        "customer_id": row.customer_id,
        "title": row.title,
        "line_of_business_id": row.line_of_business_id,
        "product_interest": row.product_interest,
        "carrier_id": row.carrier_id,
        "assigned_producer_id": row.assigned_producer_id,
        "assigned_executive_id": row.assigned_executive_id,
        "office_id": row.office_id,
        "stage_id": row.stage_id,
        "stage_code": row.stage_code,
        "estimated_premium": float(row.estimated_premium) if row.estimated_premium is not None else None,
        "probability": row.probability,
        "expected_close_date": row.expected_close_date.isoformat() if row.expected_close_date else None,
        "next_activity_at": row.next_activity_at.isoformat() if row.next_activity_at else None,
        "source_id": row.source_id,
        "referral_source_id": row.referral_source_id,
        "lost_reason_id": row.lost_reason_id,
        "notes": row.notes,
        "won_at": row.won_at.isoformat() if row.won_at else None,
        "lost_at": row.lost_at.isoformat() if row.lost_at else None,
        "reopened_at": row.reopened_at.isoformat() if row.reopened_at else None,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def activity_dict(row: CrmActivity) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "opportunity_id": row.opportunity_id,
        "prospect_id": row.prospect_id,
        "activity_type": row.activity_type,
        "title": row.title,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "status": row.status,
        "result": row.result,
        "notes": row.notes,
        "assignee_subject_id": row.assignee_subject_id,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
