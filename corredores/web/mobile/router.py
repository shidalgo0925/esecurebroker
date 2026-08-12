"""ESB GO Mobile API v1 — `/api/mobile/v1/*`."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi import HTTPException as FastAPIHTTPException
from sqlalchemy.orm import Session

from corredores.domain.models import Carrier, InsuranceLine, Party, Policy, PolicyTerm, VehicleRisk
from corredores.services.client_360 import build_client_360
from corredores.services.mobile_writes import (
    MobileWriteError,
    activity_public_dict,
    create_activity,
    document_public_dict,
    get_activity,
    get_document,
    list_activities,
    list_documents,
    upload_document,
)
from corredores.services.tenant import assert_membership, list_accessible_organizations
from corredores.services.today_home import build_today_home
from corredores.web.auth_session import actor_id_for_username, verify_credentials
from corredores.services.access_control import (
    AccessDenied,
    apply_scope_to_party_query,
    apply_scope_to_policy_query,
    require_party_in_scope,
    require_policy_in_scope,
    scope_allowlists,
)
from corredores.web.mobile.deps import (
    MobileContext,
    get_db,
    map_access_denied,
    require_access,
    require_org_context,
)
from corredores.web.mobile.errors import MobileAPIError
from corredores.web.mobile.permissions import entitlements_payload
from corredores.web.mobile.schemas import (
    ActivityCreateRequest,
    ActivityListResponse,
    ActivityOut,
    AttentionCardOut,
    Customer360Response,
    CustomerDetailResponse,
    CustomerListItem,
    CustomerListResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentOut,
    IdentityOut,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    MembershipOut,
    MoneyCardOut,
    OpportunityOut,
    OrganizationOut,
    PolicyDetailResponse,
    PolicyListItem,
    PolicyListResponse,
    RefreshRequest,
    SelectOrganizationRequest,
    SessionOut,
    SystemWorkOut,
    TodayResponse,
    TokenPairResponse,
)
from corredores.web.mobile.tokens import (
    create_access_token,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/api/mobile/v1", tags=["mobile-v1"])

API_VERSION = "v1"


def _dec(v: Decimal | None) -> str | None:
    if v is None:
        return None
    return format(v, "f")


def _party_display(p: Party) -> str:
    if (p.party_type or "").upper() == "ORGANIZATION":
        return p.legal_name or p.trade_name or p.id
    return " ".join(x for x in [p.first_name or "", p.last_name or ""] if x).strip() or (
        p.legal_name or p.id
    )


def _issue_pair(
    session: Session,
    *,
    subject_id: str,
    username: str,
    organization_id: str | None,
) -> TokenPairResponse:
    orgs = list_accessible_organizations(session, subject_id, username=username)
    bound_org = organization_id
    if bound_org is None and len(orgs) == 1:
        bound_org = orgs[0]["organization_id"]
    access, exp = create_access_token(
        subject_id=subject_id,
        username=username,
        organization_id=bound_org,
    )
    refresh, _ = issue_refresh_token(
        session,
        subject_id=subject_id,
        username=username,
        organization_id=bound_org,
    )
    needs = bound_org is None and len(orgs) > 1
    return TokenPairResponse(
        access_token=access,
        refresh_token=refresh,
        expires_at=exp,
        organization_id=bound_org,
        requires_organization_selection=needs,
        organizations=orgs if needs else ([] if bound_org else orgs),
    )


@router.get(
    "/health",
    summary="Mobile API health",
    response_model=dict[str, str],
)
def mobile_health() -> dict[str, str]:
    return {"status": "ok", "api": "mobile", "version": API_VERSION}


@router.post(
    "/auth/login",
    response_model=TokenPairResponse,
    summary="Mobile login (JSON)",
    responses={401: {"description": "Invalid credentials"}},
)
def mobile_login(body: LoginRequest, session: Session = Depends(get_db)) -> TokenPairResponse:
    cred = verify_credentials(body.username, body.password)
    if cred is None:
        raise MobileAPIError("invalid_credentials", "Invalid username or password.", status_code=401)
    subject_id = actor_id_for_username(cred.username)
    orgs = list_accessible_organizations(session, subject_id, username=cred.username)
    org_id: str | None = None
    if len(orgs) == 1:
        org_id = orgs[0]["organization_id"]
    return _issue_pair(
        session,
        subject_id=subject_id,
        username=cred.username,
        organization_id=org_id,
    )


@router.post(
    "/auth/refresh",
    response_model=TokenPairResponse,
    summary="Rotate refresh token and issue new access token",
)
def mobile_refresh(body: RefreshRequest, session: Session = Depends(get_db)) -> TokenPairResponse:
    new_raw, old, new_row = rotate_refresh_token(session, body.refresh_token)
    access, exp = create_access_token(
        subject_id=old.subject_id,
        username=old.username,
        organization_id=new_row.organization_id,
    )
    orgs = list_accessible_organizations(session, old.subject_id, username=old.username)
    needs = new_row.organization_id is None and len(orgs) > 1
    return TokenPairResponse(
        access_token=access,
        refresh_token=new_raw,
        expires_at=exp,
        organization_id=new_row.organization_id,
        requires_organization_selection=needs,
        organizations=orgs if needs else [],
    )


@router.post("/auth/logout", summary="Revoke refresh token")
def mobile_logout(body: LogoutRequest, session: Session = Depends(get_db)) -> dict[str, bool]:
    if body.refresh_token:
        revoke_refresh_token(session, body.refresh_token)
    return {"ok": True}


@router.post(
    "/session/organization",
    response_model=TokenPairResponse,
    summary="Select organization (requires membership; re-issues tokens)",
)
def select_organization(
    body: SelectOrganizationRequest,
    ctx: MobileContext = Depends(require_access),
    session: Session = Depends(get_db),
) -> TokenPairResponse:
    try:
        assert_membership(
            session,
            ctx.principal.subject_id,
            body.organization_id,
            username=ctx.principal.username,
        )
    except FastAPIHTTPException as e:
        raise MobileAPIError(
            "forbidden",
            "No membership for this organization.",
            status_code=403,
        ) from e
    # Issue fresh pair bound to org (old refresh still valid until client switches — accept)
    return _issue_pair(
        session,
        subject_id=ctx.principal.subject_id,
        username=ctx.principal.username,
        organization_id=body.organization_id,
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Current mobile session context",
)
def mobile_me(
    ctx: MobileContext = Depends(require_access),
    session: Session = Depends(get_db),
) -> MeResponse:
    from corredores.services.saas_signup import find_account_by_subject

    acc = find_account_by_subject(session, ctx.principal.subject_id)
    display = acc.display_name if acc else None
    if ctx.access is not None:
        role = ctx.access.role
        scope = ctx.access.scope
        perms = sorted(ctx.access.permissions)
        producer_profile_id = ctx.access.producer_profile_id
    else:
        role = "PLATFORM" if ctx.is_platform else "BROKER"
        scope = "ORGANIZATION"
        from corredores.services.access_control import permissions_for_role

        perms = permissions_for_role(role, is_platform=ctx.is_platform)
        producer_profile_id = None
    ents = entitlements_payload(
        session, ctx.organization.id if ctx.organization else None
    )
    orgs = list_accessible_organizations(
        session, ctx.principal.subject_id, username=ctx.principal.username
    )
    return MeResponse(
        identity=IdentityOut(
            subject_id=ctx.principal.subject_id,
            username=ctx.principal.username,
            display_name=display,
        ),
        organization=(
            OrganizationOut(
                id=ctx.organization.id,
                name=ctx.organization.name,
                active=ctx.organization.active,
            )
            if ctx.organization
            else None
        ),
        membership=(
            MembershipOut(
                id=ctx.membership.id if ctx.membership else None,
                role_code=role,
                active=True,
            )
            if ctx.organization
            else None
        ),
        role=role,
        scope=scope,  # type: ignore[arg-type]
        permissions=perms,
        entitlements=ents,
        session=SessionOut(
            api_version=API_VERSION,
            scope=scope,  # type: ignore[arg-type]
            organization_selected=ctx.organization is not None,
            access_expires_at=ctx.principal.exp,
            producer_profile_id=producer_profile_id,
        ),
        organizations_available=orgs,
        producer_profile_id=producer_profile_id,
    )


@router.get("/today", response_model=TodayResponse, summary="Hoy home (mobile)")
def mobile_today(
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> TodayResponse:
    assert ctx.access is not None
    policy_ids, party_ids = scope_allowlists(session, ctx.access)
    home = build_today_home(
        session,
        ctx.organization.id,
        today=date.today(),
        policy_ids=policy_ids,
        party_ids=party_ids,
    )
    return TodayResponse(
        as_of=home.as_of.isoformat(),
        date_label=home.date_label,
        greeting=home.greeting,
        attention_count=home.attention_count,
        money=[
            MoneyCardOut(
                key=m.key,
                amount_label=m.amount_label,
                title=m.title,
                subtitle=m.subtitle,
                href=m.href,
            )
            for m in home.money
        ],
        attention=[
            AttentionCardOut(
                kind=a.kind,
                urgency=a.urgency,
                title=a.title,
                subject=a.subject,
                lines=list(a.lines),
                stamp=a.stamp,
                party_id=a.party_id,
                policy_id=a.policy_id,
                claim_id=a.claim_id,
                renewal_id=a.renewal_id,
            )
            for a in home.attention
        ],
        system_work=[
            SystemWorkOut(text=x.text, amount_label=x.amount_label) for x in home.auto_activity
        ],
        opportunities=[
            OpportunityOut(text=o.text, href=o.href) for o in home.opportunities
        ],
        auto_cuotas_managed=home.auto_cuotas_managed,
        reminders_sent_today=home.reminders_sent_today,
    )


def _match(blob: str, needle: str) -> bool:
    if not needle:
        return True
    return needle.lower() in blob.lower()


@router.get(
    "/customers",
    response_model=CustomerListResponse,
    summary="List/search customers (name, national_id, phone, email)",
)
def mobile_customers(
    q: str = Query(default="", description="Search needle"),
    party_type: str = Query(default="", description="PERSON|ORGANIZATION"),
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> CustomerListResponse:
    assert ctx.access is not None
    needle = (q or "").strip()
    tipo = (party_type or "").strip().upper()
    parties_q = apply_scope_to_party_query(
        session.query(Party), session, ctx.access
    ).order_by(Party.created_at.desc())
    parties = parties_q.limit(500).all()
    policy_counts: dict[str, int] = {}
    scoped_policies = apply_scope_to_policy_query(
        session.query(Policy), session, ctx.access
    ).all()
    for pol in scoped_policies:
        if pol.client_party_id:
            policy_counts[pol.client_party_id] = policy_counts.get(pol.client_party_id, 0) + 1
    items: list[CustomerListItem] = []
    for p in parties:
        if tipo and (p.party_type or "").upper() != tipo:
            continue
        # P0 invariant: listed customer must have ≥1 scoped policy (same gate as 360).
        # default_producer alone never grants visibility.
        if ctx.access.scope == "ASSIGNED_PORTFOLIO" and policy_counts.get(p.id, 0) < 1:
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
        items.append(
            CustomerListItem(
                id=p.id,
                name=_party_display(p),
                national_id=p.national_id,
                party_type=p.party_type or "PERSON",
                phone=p.phone,
                email=p.email,
                district=p.district,
                policies_count=policy_counts.get(p.id, 0),
            )
        )
    items = items[:100]
    return CustomerListResponse(
        items=items,
        count=len(items),
        q=needle or None,
        party_type=tipo or None,
    )


def _customer_detail(p: Party) -> CustomerDetailResponse:
    return CustomerDetailResponse(
        id=p.id,
        name=_party_display(p),
        party_type=p.party_type or "PERSON",
        national_id=p.national_id,
        phone=p.phone,
        email=p.email,
        district=p.district,
        address=p.address,
        birth_date=p.birth_date.isoformat() if p.birth_date else None,
    )


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerDetailResponse,
    summary="Customer detail (tenant enforced)",
)
def mobile_customer_detail(
    customer_id: str,
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> CustomerDetailResponse:
    assert ctx.access is not None
    try:
        p = require_party_in_scope(session, ctx.access, customer_id)
    except AccessDenied as e:
        raise map_access_denied(e) from e
    return _customer_detail(p)


@router.get(
    "/customers/{customer_id}/360",
    response_model=Customer360Response,
    summary="Customer 360",
)
def mobile_customer_360(
    customer_id: str,
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> Customer360Response:
    assert ctx.access is not None
    try:
        party = require_party_in_scope(session, ctx.access, customer_id)
    except AccessDenied as e:
        raise map_access_denied(e) from e
    try:
        snap = build_client_360(session, ctx.organization.id, party.id, today=date.today())
    except ValueError as e:
        raise MobileAPIError("not_found", "Customer not found.", status_code=404) from e

    # Same allowlist as /customers: ≥1 PRIMARY in portfolio → 360 filtrado; 0 → 404.
    # default_producer does not grant access (ADR-008 P0).
    policies = list(snap.policies)
    vehicles = list(snap.vehicles)
    renewals = list(snap.renewals)
    claims = list(snap.claims)
    policy_ids, _ = scope_allowlists(session, ctx.access)
    if policy_ids is not None:
        from corredores.domain.models import Claim, RenewalOpportunity

        policies = [x for x in policies if x.get("id") in policy_ids]
        if not policies:
            raise MobileAPIError("not_found", "Customer not found.", status_code=404)
        vis_ids = [x["id"] for x in policies]
        vis_set = set(vis_ids)
        vehicles = [v for v in vehicles if v.get("policy_id") in vis_set]
        renewals = [
            {"id": r.id, "status": r.status, "target": str(r.target_date)}
            for r in session.query(RenewalOpportunity)
            .filter(
                RenewalOpportunity.organization_id == ctx.organization.id,
                RenewalOpportunity.previous_policy_id.in_(vis_ids),
            )
            .all()
        ]
        claims = [
            {"id": c.id, "status": c.status, "number": c.claim_number}
            for c in session.query(Claim)
            .filter(
                Claim.organization_id == ctx.organization.id,
                Claim.policy_id.in_(vis_ids),
            )
            .all()
        ]

    return Customer360Response(
        customer=_customer_detail(party),
        contact={
            "phone": party.phone,
            "email": party.email,
            "address": party.address,
            "district": party.district,
            "national_id": party.national_id,
        },
        policies=policies,
        vehicles=vehicles,
        renewals=renewals,
        claims=claims,
        promises={
            "active": snap.promises_active,
            "broken": snap.promises_broken,
        },
        balance={"open": _dec(snap.balance_open), "currency": "USD"},
        gaps=[
            {
                "risk_kind": g.risk_kind,
                "label": g.label,
                "state": g.state,
                "ref_id": g.ref_id,
            }
            for g in snap.gaps
        ],
        roles=list(snap.roles),
        submissions=list(snap.submissions),
    )


@router.get("/policies", response_model=PolicyListResponse, summary="List/search policies")
def mobile_policies(
    q: str = Query(default=""),
    status: str = Query(default=""),
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> PolicyListResponse:
    assert ctx.access is not None
    needle = (q or "").strip().lower()
    st = (status or "").strip().upper()
    policies = (
        apply_scope_to_policy_query(session.query(Policy), session, ctx.access)
        .order_by(Policy.created_at.desc())
        .limit(500)
        .all()
    )
    items: list[PolicyListItem] = []
    for pol in policies:
        if st and (pol.status or "").upper() != st:
            continue
        client = session.get(Party, pol.client_party_id) if pol.client_party_id else None
        carrier = session.get(Carrier, pol.carrier_id) if pol.carrier_id else None
        line = session.get(InsuranceLine, pol.insurance_line_id) if pol.insurance_line_id else None
        term = (
            session.query(PolicyTerm)
            .filter_by(policy_id=pol.id)
            .order_by(PolicyTerm.effective_date.desc())
            .first()
        )
        client_name = _party_display(client) if client else None
        blob = " ".join(
            x
            for x in [
                pol.policy_number or "",
                client_name or "",
                carrier.name if carrier else "",
                line.code if line else "",
            ]
            if x
        ).lower()
        if needle and needle not in blob:
            continue
        items.append(
            PolicyListItem(
                id=pol.id,
                policy_number=pol.policy_number or "",
                status=pol.status or "",
                client_party_id=pol.client_party_id,
                client_name=client_name,
                carrier_name=carrier.name if carrier else None,
                line_code=line.code if line else None,
                premium=_dec(pol.gross_premium or pol.net_premium),
                effective_date=term.effective_date.isoformat() if term and term.effective_date else None,
                expiration_date=term.expiration_date.isoformat() if term and term.expiration_date else None,
            )
        )
    items = items[:100]
    return PolicyListResponse(items=items, count=len(items), q=q or None)


@router.get(
    "/policies/{policy_id}",
    response_model=PolicyDetailResponse,
    summary="Policy detail (tenant enforced)",
)
def mobile_policy_detail(
    policy_id: str,
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> PolicyDetailResponse:
    assert ctx.access is not None
    try:
        pol = require_policy_in_scope(session, ctx.access, policy_id)
    except AccessDenied as e:
        raise map_access_denied(e) from e
    client = session.get(Party, pol.client_party_id) if pol.client_party_id else None
    carrier = session.get(Carrier, pol.carrier_id) if pol.carrier_id else None
    line = session.get(InsuranceLine, pol.insurance_line_id) if pol.insurance_line_id else None
    term = (
        session.query(PolicyTerm)
        .filter_by(policy_id=pol.id)
        .order_by(PolicyTerm.effective_date.desc())
        .first()
    )
    vehicle = (
        session.query(VehicleRisk)
        .filter_by(organization_id=ctx.organization.id, policy_id=pol.id)
        .first()
    )
    veh: dict[str, Any] | None = None
    if vehicle:
        veh = {
            "id": vehicle.id,
            "plate": vehicle.plate,
            "make": vehicle.make,
            "model": vehicle.model,
            "year": vehicle.year,
        }
    return PolicyDetailResponse(
        id=pol.id,
        policy_number=pol.policy_number or "",
        status=pol.status or "",
        client_party_id=pol.client_party_id,
        client_name=_party_display(client) if client else None,
        client_national_id=client.national_id if client else None,
        carrier_id=pol.carrier_id,
        carrier_name=carrier.name if carrier else None,
        insurance_line_id=pol.insurance_line_id,
        line_code=line.code if line else None,
        net_premium=_dec(pol.net_premium),
        gross_premium=_dec(pol.gross_premium),
        annual_premium=_dec(pol.annual_premium),
        effective_date=term.effective_date.isoformat() if term and term.effective_date else None,
        expiration_date=term.expiration_date.isoformat() if term and term.expiration_date else None,
        vehicle=veh,
    )


def _map_write_error(exc: MobileWriteError) -> MobileAPIError:
    if exc.conflict:
        return MobileAPIError(exc.code, exc.message, status_code=409)
    return MobileAPIError(exc.code, exc.message, status_code=400)


@router.get(
    "/activities",
    response_model=ActivityListResponse,
    summary="List gestiones (scoped)",
)
def mobile_activities_list(
    customer_id: str = Query(default=""),
    policy_id: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=100),
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> ActivityListResponse:
    assert ctx.access is not None
    try:
        rows = list_activities(
            session,
            ctx.access,
            customer_id=customer_id.strip() or None,
            policy_id=policy_id.strip() or None,
            limit=limit,
        )
    except AccessDenied as e:
        raise map_access_denied(e) from e
    items = [ActivityOut(**activity_public_dict(r)) for r in rows]
    return ActivityListResponse(items=items, count=len(items))


@router.post(
    "/activities",
    response_model=ActivityOut,
    summary="Create gestión (requires customer context)",
)
def mobile_activities_create(
    body: ActivityCreateRequest,
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> ActivityOut:
    assert ctx.access is not None
    try:
        result = create_activity(
            session,
            ctx.access,
            customer_id=body.customer_id,
            policy_id=body.policy_id,
            activity_type=body.activity_type,
            note=body.note,
            client_activity_id=body.client_activity_id,
        )
    except AccessDenied as e:
        raise map_access_denied(e) from e
    except MobileWriteError as e:
        raise _map_write_error(e) from e
    out = activity_public_dict(result.interaction)
    out["idempotency"] = result.idempotency
    return ActivityOut(**out)


@router.get(
    "/activities/{activity_id}",
    response_model=ActivityOut,
    summary="Activity detail",
)
def mobile_activities_detail(
    activity_id: str,
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> ActivityOut:
    assert ctx.access is not None
    try:
        row = get_activity(session, ctx.access, activity_id)
    except AccessDenied as e:
        raise map_access_denied(e) from e
    return ActivityOut(**activity_public_dict(row))


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="List documents for a customer (scoped)",
)
def mobile_documents_list(
    customer_id: str = Query(..., description="Required customer context"),
    limit: int = Query(default=50, ge=1, le=100),
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> DocumentListResponse:
    assert ctx.access is not None
    try:
        rows = list_documents(session, ctx.access, customer_id=customer_id, limit=limit)
    except AccessDenied as e:
        raise map_access_denied(e) from e
    items = [
        DocumentListItem(
            document_id=d.id,
            title=d.title,
            document_type=d.doc_kind,
            original_filename=d.original_filename,
            content_type=d.content_type,
            size_bytes=d.size_bytes,
            customer_id=d.party_id,
            policy_id=d.policy_id,
            created_at=d.created_at.isoformat() if d.created_at else None,
        )
        for d in rows
    ]
    return DocumentListResponse(items=items, count=len(items), customer_id=customer_id)


@router.post(
    "/documents/upload",
    response_model=DocumentOut,
    summary="Upload document/photo (multipart, idempotent)",
)
async def mobile_documents_upload(
    customer_id: str = Form(...),
    client_upload_id: str = Form(...),
    document_type: str = Form("OTRO"),
    policy_id: str = Form(""),
    title: str = Form(""),
    file: UploadFile = File(...),
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> DocumentOut:
    assert ctx.access is not None
    raw = await file.read()
    try:
        result = upload_document(
            session,
            ctx.access,
            customer_id=customer_id,
            policy_id=policy_id.strip() or None,
            filename=file.filename or "upload.bin",
            content=raw,
            content_type=file.content_type,
            document_type=document_type,
            title=title.strip() or None,
            client_upload_id=client_upload_id,
        )
    except AccessDenied as e:
        raise map_access_denied(e) from e
    except MobileWriteError as e:
        raise _map_write_error(e) from e
    except ValueError as e:
        raise MobileAPIError("validation_error", str(e), status_code=400) from e
    return DocumentOut(**document_public_dict(result.document, idempotency=result.idempotency))


@router.get(
    "/documents/{document_id}",
    response_model=DocumentOut,
    summary="Document metadata (ACK shape)",
)
def mobile_documents_detail(
    document_id: str,
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> DocumentOut:
    assert ctx.access is not None
    try:
        doc = get_document(session, ctx.access, document_id)
    except AccessDenied as e:
        raise map_access_denied(e) from e
    return DocumentOut(**document_public_dict(doc))
