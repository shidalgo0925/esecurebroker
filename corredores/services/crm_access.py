"""ADR-011 F2 — CRM AccessContext / RBAC / anti-IDOR.

Rules (backend-enforced):
- ORGANIZATION / PLATFORM: all CRM rows in the org (with crm:* permission).
- ASSIGNED_PORTFOLIO (PRODUCER): only prospects/opportunities assigned to the
  producer profile, OR opportunities whose customer_id is in the producer portfolio,
  OR rows where assigned_executive_id == subject_id.
- Cross-org / out-of-scope → AccessDenied(not_found=True) → 404 at the edge.
- office_id: soft field only (no Office entity yet) — not used for filtering in P0.
"""

from __future__ import annotations

from sqlalchemy.orm import Query, Session

from corredores.domain.models import CrmActivity, CrmOpportunity, CrmProspect
from corredores.services.access_control import (
    SCOPE_ASSIGNED_PORTFOLIO,
    SCOPE_ORGANIZATION,
    SCOPE_PLATFORM,
    AccessContext,
    AccessDenied,
    require_permission,
    visible_portfolio_client_party_ids,
)

PERM_CRM_READ = "crm:read"
PERM_CRM_MANAGE = "crm:manage"


def _org_wide(ctx: AccessContext) -> bool:
    return ctx.scope in {SCOPE_ORGANIZATION, SCOPE_PLATFORM}


def _producer_id(ctx: AccessContext) -> str | None:
    return ctx.producer_profile_id


def _visible_customer_ids(session: Session, ctx: AccessContext) -> set[str]:
    if not ctx.producer_profile_id:
        return set()
    return visible_portfolio_client_party_ids(
        session,
        organization_id=ctx.organization_id,
        producer_profile_id=ctx.producer_profile_id,
    )


def prospect_in_scope(session: Session, ctx: AccessContext, row: CrmProspect) -> bool:
    if row.organization_id != ctx.organization_id:
        return False
    if _org_wide(ctx):
        return True
    if ctx.scope != SCOPE_ASSIGNED_PORTFOLIO:
        return False
    if row.assigned_producer_id and row.assigned_producer_id == _producer_id(ctx):
        return True
    if row.assigned_executive_id and row.assigned_executive_id == ctx.subject_id:
        return True
    return False


def opportunity_in_scope(session: Session, ctx: AccessContext, row: CrmOpportunity) -> bool:
    if row.organization_id != ctx.organization_id:
        return False
    if _org_wide(ctx):
        return True
    if ctx.scope != SCOPE_ASSIGNED_PORTFOLIO:
        return False
    if row.assigned_producer_id and row.assigned_producer_id == _producer_id(ctx):
        return True
    if row.assigned_executive_id and row.assigned_executive_id == ctx.subject_id:
        return True
    if row.customer_id and row.customer_id in _visible_customer_ids(session, ctx):
        return True
    if row.prospect_id:
        prospect = session.get(CrmProspect, row.prospect_id)
        if prospect is not None and prospect_in_scope(session, ctx, prospect):
            return True
    return False


def activity_in_scope(session: Session, ctx: AccessContext, row: CrmActivity) -> bool:
    if row.organization_id != ctx.organization_id:
        return False
    if _org_wide(ctx):
        return True
    if ctx.scope != SCOPE_ASSIGNED_PORTFOLIO:
        return False
    if row.assignee_subject_id and row.assignee_subject_id == ctx.subject_id:
        return True
    if row.opportunity_id:
        opp = session.get(CrmOpportunity, row.opportunity_id)
        if opp is not None and opportunity_in_scope(session, ctx, opp):
            return True
    if row.prospect_id:
        prospect = session.get(CrmProspect, row.prospect_id)
        if prospect is not None and prospect_in_scope(session, ctx, prospect):
            return True
    return False


def apply_scope_to_prospect_query(query: Query, session: Session, ctx: AccessContext) -> Query:
    query = query.filter(CrmProspect.organization_id == ctx.organization_id)
    if _org_wide(ctx):
        return query
    if ctx.scope != SCOPE_ASSIGNED_PORTFOLIO:
        return query.filter(CrmProspect.id.in_([]))
    pid = _producer_id(ctx)
    if not pid and not ctx.subject_id:
        return query.filter(CrmProspect.id.in_([]))
    # assigned producer OR executive subject
    from sqlalchemy import or_

    clauses = []
    if pid:
        clauses.append(CrmProspect.assigned_producer_id == pid)
    if ctx.subject_id:
        clauses.append(CrmProspect.assigned_executive_id == ctx.subject_id)
    if not clauses:
        return query.filter(CrmProspect.id.in_([]))
    return query.filter(or_(*clauses))


def apply_scope_to_opportunity_query(query: Query, session: Session, ctx: AccessContext) -> Query:
    query = query.filter(CrmOpportunity.organization_id == ctx.organization_id)
    if _org_wide(ctx):
        return query
    if ctx.scope != SCOPE_ASSIGNED_PORTFOLIO:
        return query.filter(CrmOpportunity.id.in_([]))

    from sqlalchemy import or_

    pid = _producer_id(ctx)
    cust_ids = _visible_customer_ids(session, ctx)
    clauses = []
    if pid:
        clauses.append(CrmOpportunity.assigned_producer_id == pid)
        # Prospects assigned to this producer
        from sqlalchemy import select

        sub_prospects = select(CrmProspect.id).where(
            CrmProspect.organization_id == ctx.organization_id,
            CrmProspect.assigned_producer_id == pid,
        )
        clauses.append(CrmOpportunity.prospect_id.in_(sub_prospects))
    if ctx.subject_id:
        clauses.append(CrmOpportunity.assigned_executive_id == ctx.subject_id)
    if cust_ids:
        clauses.append(CrmOpportunity.customer_id.in_(list(cust_ids)))
    if not clauses:
        return query.filter(CrmOpportunity.id.in_([]))
    return query.filter(or_(*clauses))


def apply_scope_to_activity_query(query: Query, session: Session, ctx: AccessContext) -> Query:
    query = query.filter(CrmActivity.organization_id == ctx.organization_id)
    if _org_wide(ctx):
        return query
    if ctx.scope != SCOPE_ASSIGNED_PORTFOLIO:
        return query.filter(CrmActivity.id.in_([]))

    from sqlalchemy import or_

    opp_ids = [
        r[0]
        for r in apply_scope_to_opportunity_query(
            session.query(CrmOpportunity.id), session, ctx
        ).all()
    ]
    prosp_ids = [
        r[0]
        for r in apply_scope_to_prospect_query(
            session.query(CrmProspect.id), session, ctx
        ).all()
    ]
    clauses = []
    if opp_ids:
        clauses.append(CrmActivity.opportunity_id.in_(opp_ids))
    if prosp_ids:
        clauses.append(CrmActivity.prospect_id.in_(prosp_ids))
    if ctx.subject_id:
        clauses.append(CrmActivity.assignee_subject_id == ctx.subject_id)
    if not clauses:
        return query.filter(CrmActivity.id.in_([]))
    return query.filter(or_(*clauses))


def require_prospect_in_scope(
    session: Session, ctx: AccessContext, prospect_id: str
) -> CrmProspect:
    require_permission(ctx, PERM_CRM_READ)
    row = session.get(CrmProspect, prospect_id)
    if row is None or not prospect_in_scope(session, ctx, row):
        raise AccessDenied("not found", not_found=True)
    return row


def require_opportunity_in_scope(
    session: Session, ctx: AccessContext, opportunity_id: str
) -> CrmOpportunity:
    require_permission(ctx, PERM_CRM_READ)
    row = session.get(CrmOpportunity, opportunity_id)
    if row is None or not opportunity_in_scope(session, ctx, row):
        raise AccessDenied("not found", not_found=True)
    return row


def require_activity_in_scope(
    session: Session, ctx: AccessContext, activity_id: str
) -> CrmActivity:
    require_permission(ctx, PERM_CRM_READ)
    row = session.get(CrmActivity, activity_id)
    if row is None or not activity_in_scope(session, ctx, row):
        raise AccessDenied("not found", not_found=True)
    return row


def require_crm_manage(ctx: AccessContext) -> None:
    require_permission(ctx, PERM_CRM_MANAGE)
