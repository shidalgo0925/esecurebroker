"""ESB GO Mobile API v1 — `/api/mobile/v1/*`."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException as FastAPIHTTPException
from sqlalchemy.orm import Session

from corredores.domain.models import Carrier, InsuranceLine, Party, Policy, PolicyTerm, VehicleRisk
from corredores.services.client_360 import build_client_360
from corredores.services.saas_signup import find_account_by_subject
from corredores.services.tenant import (
    assert_membership,
    list_accessible_organizations,
    require_org_owned,
)
from corredores.services.today_home import build_today_home
from corredores.web.auth_session import actor_id_for_username, verify_credentials
from corredores.web.mobile.deps import MobileContext, get_db, require_access, require_org_context
from corredores.web.mobile.errors import MobileAPIError
from corredores.web.mobile.permissions import (
    SCOPE_ORGANIZATION,
    entitlements_payload,
    permissions_for_role,
)
from corredores.web.mobile.schemas import (
    AttentionCardOut,
    Customer360Response,
    CustomerDetailResponse,
    CustomerListItem,
    CustomerListResponse,
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
    acc = find_account_by_subject(session, ctx.principal.subject_id)
    display = acc.display_name if acc else None
    role = ctx.role_code if ctx.organization else (
        "PLATFORM" if ctx.is_platform else "BROKER"
    )
    if role not in {"OWNER", "BROKER", "PLATFORM"}:
        # Unknown stored role — still return raw but permissions use base set
        pass
    perms = permissions_for_role(role, is_platform=ctx.is_platform)
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
        scope=SCOPE_ORGANIZATION,  # type: ignore[arg-type]
        permissions=perms,
        entitlements=ents,
        session=SessionOut(
            api_version=API_VERSION,
            scope=SCOPE_ORGANIZATION,  # type: ignore[arg-type]
            organization_selected=ctx.organization is not None,
            access_expires_at=ctx.principal.exp,
        ),
        organizations_available=orgs,
    )


@router.get("/today", response_model=TodayResponse, summary="Hoy home (mobile)")
def mobile_today(
    ctx: MobileContext = Depends(require_org_context),
    session: Session = Depends(get_db),
) -> TodayResponse:
    home = build_today_home(session, ctx.organization.id, today=date.today())
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
    org_id = ctx.organization.id
    needle = (q or "").strip()
    tipo = (party_type or "").strip().upper()
    parties = (
        session.query(Party)
        .filter_by(organization_id=org_id)
        .order_by(Party.created_at.desc())
        .limit(500)
        .all()
    )
    policy_counts: dict[str, int] = {}
    for pol in session.query(Policy).filter_by(organization_id=org_id).all():
        if pol.client_party_id:
            policy_counts[pol.client_party_id] = policy_counts.get(pol.client_party_id, 0) + 1
    items: list[CustomerListItem] = []
    for p in parties:
        if tipo and (p.party_type or "").upper() != tipo:
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
    try:
        p = require_org_owned(session, Party, customer_id, ctx.organization.id)
    except FastAPIHTTPException as e:
        raise MobileAPIError("not_found", "Customer not found.", status_code=404) from e
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
    try:
        p = require_org_owned(session, Party, customer_id, ctx.organization.id)
    except FastAPIHTTPException as e:
        raise MobileAPIError("not_found", "Customer not found.", status_code=404) from e
    try:
        snap = build_client_360(session, ctx.organization.id, p.id, today=date.today())
    except ValueError as e:
        raise MobileAPIError("not_found", "Customer not found.", status_code=404) from e
    return Customer360Response(
        customer=_customer_detail(p),
        contact={
            "phone": p.phone,
            "email": p.email,
            "address": p.address,
            "district": p.district,
            "national_id": p.national_id,
        },
        policies=list(snap.policies),
        vehicles=list(snap.vehicles),
        renewals=list(snap.renewals),
        claims=list(snap.claims),
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
    org_id = ctx.organization.id
    needle = (q or "").strip().lower()
    st = (status or "").strip().upper()
    policies = (
        session.query(Policy)
        .filter_by(organization_id=org_id)
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
    try:
        pol = require_org_owned(session, Policy, policy_id, ctx.organization.id)
    except FastAPIHTTPException as e:
        raise MobileAPIError("not_found", "Policy not found.", status_code=404) from e
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
