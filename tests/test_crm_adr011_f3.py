"""ADR-011 F3 — CRM service API (prospect → opportunity → activity → WON → convert)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.enums import PartyType
from corredores.domain.membership_roles import OWNER, PRODUCER
from corredores.domain.models import (
    AuditEvent,
    BrokerAccount,
    CrmLostReason,
    CrmProspect,
    OrgSubscription,
    Party,
    PartyRole,
)
from corredores.domain.enums import PartyRoleType
from corredores.services.access_control import AccessDenied, resolve_access_context
from corredores.services.crm_catalog_seed import ensure_default_crm_catalogs
from corredores.services.crm_service import (
    convert_opportunity_to_customer,
    create_activity,
    create_opportunity,
    create_prospect,
    list_opportunities,
    mark_lost,
    mark_won,
    set_opportunity_stage,
)
from corredores.services.producer_portfolio import create_producer_profile
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
    ensure_default_crm_catalogs(session, org)
    if session.query(OrgSubscription).filter_by(organization_id=org).one_or_none() is None:
        session.add(
            OrgSubscription(
                organization_id=org,
                plan_code="oficina",
                status="active",
                billing_provider="piloto",
            )
        )
    owner_email = "owner.f3@example.invalid"
    owner_subj = actor_id_for_username(owner_email)
    session.add(
        BrokerAccount(
            email=owner_email,
            password_hash=hash_password("secreto123"),
            display_name="Owner F3",
            subject_id=owner_subj,
            active=True,
        )
    )
    ensure_membership(
        session, subject_id=owner_subj, organization_id=org, role_code=OWNER, display_name="Owner"
    )
    # Producer A
    prod_email = "prod.a.f3@example.invalid"
    prod_subj = actor_id_for_username(prod_email)
    person = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Prod",
        last_name="A",
        email=prod_email,
    )
    session.add(person)
    session.flush()
    session.add(
        BrokerAccount(
            email=prod_email,
            password_hash=hash_password("secreto123"),
            display_name="Prod A",
            subject_id=prod_subj,
            active=True,
        )
    )
    ensure_membership(
        session, subject_id=prod_subj, organization_id=org, role_code=PRODUCER, display_name="A"
    )
    profile = create_producer_profile(
        session, organization_id=org, party_id=person.id, code="PA3"
    )
    # Producer B
    prod_b_email = "prod.b.f3@example.invalid"
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
        session, subject_id=prod_b_subj, organization_id=org, role_code=PRODUCER, display_name="B"
    )
    create_producer_profile(session, organization_id=org, party_id=person_b.id, code="PB3")
    session.commit()
    info["owner_email"] = owner_email
    info["prod_email"] = prod_email
    info["prod_b_email"] = prod_b_email
    info["profile_a"] = profile.id
    return info


def _owner_ctx(session, world):
    return resolve_access_context(
        session,
        subject_id=actor_id_for_username(world["owner_email"]),
        username=world["owner_email"],
        organization_id=world["alfa"]["organization_id"],
    )


def _prod_ctx(session, world, email_key="prod_email"):
    return resolve_access_context(
        session,
        subject_id=actor_id_for_username(world[email_key]),
        username=world[email_key],
        organization_id=world["alfa"]["organization_id"],
    )


def test_gate_prospect_to_customer(session, world):
    org = world["alfa"]["organization_id"]
    ctx = _owner_ctx(session, world)
    referrer = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="María",
        last_name="González",
        email="maria.ref@example.com",
    )
    session.add(referrer)
    session.flush()
    ensure_default_crm_catalogs(session, org)
    from corredores.domain.models import CrmLeadSource

    src = session.query(CrmLeadSource).filter_by(organization_id=org, code="REFERRAL").one()
    prosp = create_prospect(
        session,
        ctx,
        organization_id=org,
        first_name="Juan",
        last_name="Pérez",
        phone="6000-9999",
        email="juan.perez.f3@example.com",
        source_id=src.id,
        referral_source_id=referrer.id,
        assigned_producer_id=world["profile_a"],
        actor_id="owner",
    )
    opp = create_opportunity(
        session,
        ctx,
        organization_id=org,
        prospect_id=prosp.id,
        title="Auto Juan Pérez",
        product_interest="AUTO",
        estimated_premium=Decimal("620.00"),
        assigned_producer_id=world["profile_a"],
        actor_id="owner",
    )
    act = create_activity(
        session,
        ctx,
        organization_id=org,
        opportunity_id=opp.id,
        prospect_id=prosp.id,
        activity_type="CALL",
        title="Llamar hoy 3:00 PM",
        due_at=datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc),
        actor_id="owner",
    )
    set_opportunity_stage(
        session, ctx, organization_id=org, opportunity_id=opp.id, stage_code="CONTACTED", actor_id="o"
    )
    set_opportunity_stage(
        session, ctx, organization_id=org, opportunity_id=opp.id, stage_code="QUOTING", actor_id="o"
    )
    mark_won(session, ctx, organization_id=org, opportunity_id=opp.id, actor_id="o")
    opp2, customer, action = convert_opportunity_to_customer(
        session, ctx, organization_id=org, opportunity_id=opp.id, actor_id="o"
    )
    assert action == "CREATE"
    assert opp2.customer_id == customer.id
    assert session.get(CrmProspect, prosp.id).status == "CONVERTED"
    assert session.get(CrmProspect, prosp.id).converted_customer_id == customer.id
    role = (
        session.query(PartyRole)
        .filter_by(party_id=customer.id, role_type=PartyRoleType.CLIENT)
        .one_or_none()
    )
    assert role is not None
    # Prospect + opportunity retained
    assert session.get(CrmProspect, prosp.id) is not None
    assert session.get(type(opp), opp.id) is not None
    audits = (
        session.query(AuditEvent)
        .filter_by(organization_id=org, entity_id=opp.id)
        .all()
    )
    actions = {a.action for a in audits}
    assert "CRM_OPPORTUNITY_WON" in actions
    assert "CRM_CONVERTED_TO_CUSTOMER" in actions
    assert act.id


def test_existing_customer_opportunity_no_new_prospect(session, world):
    org = world["alfa"]["organization_id"]
    ctx = _owner_ctx(session, world)
    customer = Party(
        organization_id=org,
        party_type=PartyType.PERSON,
        first_name="Ana",
        last_name="Cliente",
        email="ana.cliente@example.com",
    )
    session.add(customer)
    session.flush()
    session.add(
        PartyRole(
            organization_id=org,
            party_id=customer.id,
            role_type=PartyRoleType.CLIENT,
            context_type="GLOBAL",
        )
    )
    n_before = session.query(CrmProspect).filter_by(organization_id=org).count()
    opp = create_opportunity(
        session,
        ctx,
        organization_id=org,
        customer_id=customer.id,
        title="Vida Ana Cliente",
        product_interest="VIDA",
        actor_id="owner",
    )
    assert opp.prospect_id is None
    assert opp.customer_id == customer.id
    assert session.query(CrmProspect).filter_by(organization_id=org).count() == n_before


def test_producer_b_cannot_read_a_opportunity(session, world):
    org = world["alfa"]["organization_id"]
    owner = _owner_ctx(session, world)
    prosp = create_prospect(
        session,
        owner,
        organization_id=org,
        first_name="Solo",
        last_name="A",
        mobile="6111-0000",
        assigned_producer_id=world["profile_a"],
        actor_id="o",
    )
    opp = create_opportunity(
        session,
        owner,
        organization_id=org,
        prospect_id=prosp.id,
        title="Solo A",
        assigned_producer_id=world["profile_a"],
        actor_id="o",
    )
    ctx_b = _prod_ctx(session, world, "prod_b_email")
    with pytest.raises(AccessDenied) as ei:
        from corredores.services.crm_service import get_opportunity

        get_opportunity(session, ctx_b, org, opp.id)
    assert ei.value.not_found is True
    ids = {o.id for o in list_opportunities(session, ctx_b, org)}
    assert opp.id not in ids


def test_lost_requires_reason_and_reopen(session, world):
    org = world["alfa"]["organization_id"]
    ctx = _owner_ctx(session, world)
    prosp = create_prospect(
        session, ctx, organization_id=org, first_name="X", phone="6000-1", actor_id="o"
    )
    opp = create_opportunity(
        session, ctx, organization_id=org, prospect_id=prosp.id, title="X Auto", actor_id="o"
    )
    reason = session.query(CrmLostReason).filter_by(organization_id=org, code="PRICE").one()
    lost = mark_lost(
        session,
        ctx,
        organization_id=org,
        opportunity_id=opp.id,
        lost_reason_id=reason.id,
        actor_id="o",
    )
    assert lost.stage_code == "LOST"
    from corredores.services.crm_service import reopen_opportunity

    reopened = reopen_opportunity(
        session, ctx, organization_id=org, opportunity_id=opp.id, actor_id="o"
    )
    assert reopened.stage_code == "NEGOTIATION"
    assert reopened.reopened_at is not None
