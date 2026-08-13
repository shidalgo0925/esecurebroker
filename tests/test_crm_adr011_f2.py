"""ADR-011 F2 — CRM AccessContext / RBAC / anti-IDOR."""

from __future__ import annotations

from datetime import date

import pytest

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.enums import PartyType
from corredores.domain.membership_roles import OWNER, PRODUCER
from corredores.domain.models import (
    BrokerAccount,
    CrmActivity,
    CrmOpportunity,
    CrmProspect,
    OrgSubscription,
    Party,
)
from corredores.services.access_control import AccessDenied, resolve_access_context
from corredores.services.crm_access import (
    apply_scope_to_opportunity_query,
    apply_scope_to_prospect_query,
    require_activity_in_scope,
    require_opportunity_in_scope,
    require_prospect_in_scope,
)
from corredores.services.crm_catalog_seed import ensure_default_crm_catalogs
from corredores.services.producer_portfolio import assign_policy_primary, create_producer_profile
from corredores.services.saas_signup import hash_password
from corredores.services.seed_tenants import seed_multitenant_demo
from corredores.services.tenant import ensure_membership
from corredores.web.auth_session import actor_id_for_username


@pytest.fixture()
def session():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as s:
        yield s
        s.rollback()


@pytest.fixture()
def world(session):
    info = seed_multitenant_demo(session, today=date(2026, 8, 10))
    org = info["alfa"]["organization_id"]
    for oid in (info["alfa"]["organization_id"], info["beta"]["organization_id"]):
        if session.query(OrgSubscription).filter_by(organization_id=oid).one_or_none() is None:
            session.add(
                OrgSubscription(
                    organization_id=oid,
                    plan_code="oficina",
                    status="active",
                    billing_provider="piloto",
                )
            )
        ensure_default_crm_catalogs(session, oid)

    owner_email = "owner.crm@example.invalid"
    owner_subj = actor_id_for_username(owner_email)
    session.add(
        BrokerAccount(
            email=owner_email,
            password_hash=hash_password("secreto123"),
            display_name="Owner CRM",
            subject_id=owner_subj,
            active=True,
        )
    )
    ensure_membership(
        session, subject_id=owner_subj, organization_id=org, role_code=OWNER, display_name="Owner"
    )

    # Producer A — gets assigned CRM rows
    prod_a_email = "prod.a.crm@example.invalid"
    prod_a_subj = actor_id_for_username(prod_a_email)
    person_a = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Prod",
        last_name="A",
        email=prod_a_email,
    )
    session.add(person_a)
    session.flush()
    session.add(
        BrokerAccount(
            email=prod_a_email,
            password_hash=hash_password("secreto123"),
            display_name="Prod A",
            subject_id=prod_a_subj,
            active=True,
        )
    )
    ensure_membership(
        session,
        subject_id=prod_a_subj,
        organization_id=org,
        role_code=PRODUCER,
        display_name="Prod A",
    )
    profile_a = create_producer_profile(
        session, organization_id=org, party_id=person_a.id, code="PA"
    )
    assign_policy_primary(
        session,
        organization_id=org,
        producer_profile_id=profile_a.id,
        policy_id=info["alfa"]["policy_id"],
    )

    # Producer B — other portfolio
    prod_b_email = "prod.b.crm@example.invalid"
    prod_b_subj = actor_id_for_username(prod_b_email)
    person_b = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Prod",
        last_name="B",
        email=prod_b_email,
    )
    session.add(person_b)
    session.flush()
    session.add(
        BrokerAccount(
            email=prod_b_email,
            password_hash=hash_password("secreto123"),
            display_name="Prod B",
            subject_id=prod_b_subj,
            active=True,
        )
    )
    ensure_membership(
        session,
        subject_id=prod_b_subj,
        organization_id=org,
        role_code=PRODUCER,
        display_name="Prod B",
    )
    profile_b = create_producer_profile(
        session, organization_id=org, party_id=person_b.id, code="PB"
    )

    # Prospect + opportunity for A
    prosp_a = CrmProspect(
        organization_id=org,
        first_name="Juan",
        last_name="Pérez",
        phone="6000-1111",
        assigned_producer_id=profile_a.id,
    )
    session.add(prosp_a)
    session.flush()
    opp_a = CrmOpportunity(
        organization_id=org,
        prospect_id=prosp_a.id,
        title="Auto Juan",
        stage_code="NEW",
        assigned_producer_id=profile_a.id,
    )
    session.add(opp_a)
    session.flush()
    act_a = CrmActivity(
        organization_id=org,
        opportunity_id=opp_a.id,
        prospect_id=prosp_a.id,
        activity_type="CALL",
        title="Llamar",
        status="PENDING",
        assignee_subject_id=prod_a_subj,
    )
    session.add(act_a)

    # Prospect + opportunity for B (anti-IDOR target)
    prosp_b = CrmProspect(
        organization_id=org,
        first_name="Otro",
        last_name="Lead",
        phone="6000-2222",
        assigned_producer_id=profile_b.id,
    )
    session.add(prosp_b)
    session.flush()
    opp_b = CrmOpportunity(
        organization_id=org,
        prospect_id=prosp_b.id,
        title="Vida Otro",
        stage_code="NEW",
        assigned_producer_id=profile_b.id,
    )
    session.add(opp_b)

    # Cross-sell opportunity on existing customer in A's portfolio (no prospect)
    opp_xsell = CrmOpportunity(
        organization_id=org,
        customer_id=info["alfa"]["party_id"],
        title="Vida cliente cartera A",
        stage_code="NEW",
        product_interest="VIDA",
    )
    session.add(opp_xsell)
    session.commit()

    info["owner_email"] = owner_email
    info["prod_a_email"] = prod_a_email
    info["prod_b_email"] = prod_b_email
    info["profile_a"] = profile_a.id
    info["profile_b"] = profile_b.id
    info["prosp_a"] = prosp_a.id
    info["prosp_b"] = prosp_b.id
    info["opp_a"] = opp_a.id
    info["opp_b"] = opp_b.id
    info["opp_xsell"] = opp_xsell.id
    info["act_a"] = act_a.id
    return info


def test_owner_sees_all_crm(session, world):
    ctx = resolve_access_context(
        session,
        subject_id=actor_id_for_username(world["owner_email"]),
        username=world["owner_email"],
        organization_id=world["alfa"]["organization_id"],
    )
    assert "crm:read" in ctx.permissions
    assert "crm:manage" in ctx.permissions
    require_prospect_in_scope(session, ctx, world["prosp_a"])
    require_prospect_in_scope(session, ctx, world["prosp_b"])
    require_opportunity_in_scope(session, ctx, world["opp_b"])
    rows = apply_scope_to_prospect_query(session.query(CrmProspect), session, ctx).all()
    assert {r.id for r in rows} >= {world["prosp_a"], world["prosp_b"]}


def test_producer_a_sees_assigned_only(session, world):
    ctx = resolve_access_context(
        session,
        subject_id=actor_id_for_username(world["prod_a_email"]),
        username=world["prod_a_email"],
        organization_id=world["alfa"]["organization_id"],
    )
    assert ctx.producer_profile_id == world["profile_a"]
    require_prospect_in_scope(session, ctx, world["prosp_a"])
    require_opportunity_in_scope(session, ctx, world["opp_a"])
    require_activity_in_scope(session, ctx, world["act_a"])
    # Cross-sell on portfolio customer
    require_opportunity_in_scope(session, ctx, world["opp_xsell"])

    prosp_ids = {
        r.id
        for r in apply_scope_to_prospect_query(session.query(CrmProspect), session, ctx).all()
    }
    assert world["prosp_a"] in prosp_ids
    assert world["prosp_b"] not in prosp_ids

    opp_ids = {
        r.id
        for r in apply_scope_to_opportunity_query(
            session.query(CrmOpportunity), session, ctx
        ).all()
    }
    assert world["opp_a"] in opp_ids
    assert world["opp_xsell"] in opp_ids
    assert world["opp_b"] not in opp_ids


def test_producer_b_anti_idor_404(session, world):
    """Producer B cannot see Producer A opportunity → AccessDenied not_found (404)."""
    ctx = resolve_access_context(
        session,
        subject_id=actor_id_for_username(world["prod_b_email"]),
        username=world["prod_b_email"],
        organization_id=world["alfa"]["organization_id"],
    )
    with pytest.raises(AccessDenied) as ei:
        require_opportunity_in_scope(session, ctx, world["opp_a"])
    assert ei.value.not_found is True

    with pytest.raises(AccessDenied) as ei2:
        require_prospect_in_scope(session, ctx, world["prosp_a"])
    assert ei2.value.not_found is True

    with pytest.raises(AccessDenied) as ei3:
        require_activity_in_scope(session, ctx, world["act_a"])
    assert ei3.value.not_found is True


def test_missing_permission_denied(session, world):
    from dataclasses import replace

    ctx = resolve_access_context(
        session,
        subject_id=actor_id_for_username(world["prod_a_email"]),
        username=world["prod_a_email"],
        organization_id=world["alfa"]["organization_id"],
    )
    # strip crm:* to simulate custom role gap
    ctx = replace(
        ctx,
        permissions=frozenset(p for p in ctx.permissions if not p.startswith("crm:")),
    )
    with pytest.raises(AccessDenied) as ei:
        require_prospect_in_scope(session, ctx, world["prosp_a"])
    assert "crm:read" in str(ei.value)
