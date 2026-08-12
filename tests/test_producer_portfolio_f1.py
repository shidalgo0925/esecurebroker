"""ADR-008 F1 — ProducerProfile + PortfolioAssignment schema/integrity."""

from __future__ import annotations

from datetime import date

import pytest

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.enums import PartyRoleType, PartyType
from corredores.domain.membership_roles import CANONICAL_ROLE_CODES, PRODUCER
from corredores.domain.models import OrgMembership, Organization, Party, PartyRole, Policy
from corredores.services.producer_portfolio import (
    ProducerPortfolioError,
    assign_policy_primary,
    create_producer_profile,
    set_default_producer,
)
from corredores.services.seed_tenants import seed_multitenant_demo


@pytest.fixture()
def session():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as s:
        yield s
        s.rollback()


@pytest.fixture()
def multi(session):
    return seed_multitenant_demo(session, today=date(2026, 8, 10))


def _person(session, org_id: str, first: str, last: str) -> Party:
    p = Party(
        organization_id=org_id,
        party_type=PartyType.PERSON,
        first_name=first,
        last_name=last,
    )
    session.add(p)
    session.flush()
    return p


def test_create_producer_without_membership(session, multi):
    org_id = multi["alfa"]["organization_id"]
    person = _person(session, org_id, "Carlos", "Agente")
    profile = create_producer_profile(
        session,
        organization_id=org_id,
        party_id=person.id,
        code="CARLOS",
    )
    assert profile.id
    assert profile.organization_id == org_id
    assert profile.party_id == person.id
    assert profile.status == "ACTIVE"
    # No membership required
    mems = session.query(OrgMembership).filter_by(organization_id=org_id).all()
    assert not any(m.role_code == PRODUCER for m in mems)
    # AGENT PartyRole synced
    agent = (
        session.query(PartyRole)
        .filter_by(
            organization_id=org_id,
            party_id=person.id,
            role_type=PartyRoleType.AGENT,
            context_type="GLOBAL",
        )
        .one_or_none()
    )
    assert agent is not None


def test_producer_linked_to_party(session, multi):
    org_id = multi["alfa"]["organization_id"]
    person = _person(session, org_id, "Ana", "Prod")
    profile = create_producer_profile(
        session, organization_id=org_id, party_id=person.id, display_name="Ana Prod"
    )
    assert profile.display_name == "Ana Prod"
    assert session.get(Party, profile.party_id).first_name == "Ana"


def test_assign_policy_primary(session, multi):
    org_id = multi["alfa"]["organization_id"]
    person = _person(session, org_id, "Carlos", "A")
    profile = create_producer_profile(session, organization_id=org_id, party_id=person.id)
    pol_id = multi["alfa"]["policy_id"]
    a = assign_policy_primary(
        session,
        organization_id=org_id,
        producer_profile_id=profile.id,
        policy_id=pol_id,
        reason="initial",
        assigned_by_subject_id="piloto:test",
    )
    assert a.assignment_role == "PRIMARY"
    assert a.target_type == "POLICY"
    assert a.target_id == pol_id
    assert a.effective_to is None


def test_second_active_primary_rejected(session, multi):
    org_id = multi["alfa"]["organization_id"]
    p1 = create_producer_profile(
        session, organization_id=org_id, party_id=_person(session, org_id, "C", "1").id, code="C1"
    )
    p2 = create_producer_profile(
        session, organization_id=org_id, party_id=_person(session, org_id, "C", "2").id, code="C2"
    )
    pol_id = multi["alfa"]["policy_id"]
    assign_policy_primary(
        session, organization_id=org_id, producer_profile_id=p1.id, policy_id=pol_id
    )
    with pytest.raises(ProducerPortfolioError, match="PRIMARY"):
        assign_policy_primary(
            session,
            organization_id=org_id,
            producer_profile_id=p2.id,
            policy_id=pol_id,
            close_existing=False,
        )


def test_reassign_closes_history(session, multi):
    org_id = multi["alfa"]["organization_id"]
    p1 = create_producer_profile(
        session, organization_id=org_id, party_id=_person(session, org_id, "C", "1").id, code="H1"
    )
    p2 = create_producer_profile(
        session, organization_id=org_id, party_id=_person(session, org_id, "A", "2").id, code="H2"
    )
    pol_id = multi["alfa"]["policy_id"]
    a1 = assign_policy_primary(
        session, organization_id=org_id, producer_profile_id=p1.id, policy_id=pol_id
    )
    a2 = assign_policy_primary(
        session,
        organization_id=org_id,
        producer_profile_id=p2.id,
        policy_id=pol_id,
        reason="Carlos left",
        close_existing=True,
    )
    session.refresh(a1)
    assert a1.effective_to is not None
    assert a2.effective_to is None
    assert a2.producer_profile_id == p2.id
    assert a1.id != a2.id


def test_cross_org_assignment_rejected(session, multi):
    alfa = multi["alfa"]["organization_id"]
    beta = multi["beta"]["organization_id"]
    person = _person(session, alfa, "X", "Y")
    profile = create_producer_profile(session, organization_id=alfa, party_id=person.id)
    with pytest.raises(ProducerPortfolioError, match="cross-organization"):
        assign_policy_primary(
            session,
            organization_id=alfa,
            producer_profile_id=profile.id,
            policy_id=multi["beta"]["policy_id"],
        )
    # producer org mismatch
    with pytest.raises(ProducerPortfolioError):
        assign_policy_primary(
            session,
            organization_id=beta,
            producer_profile_id=profile.id,
            policy_id=multi["beta"]["policy_id"],
        )


def test_legacy_without_producer_still_works(session, multi):
    org = session.get(Organization, multi["alfa"]["organization_id"])
    assert org is not None
    pol = session.get(Policy, multi["alfa"]["policy_id"])
    assert pol is not None
    assert pol.organization_id == org.id
    # No assignments required
    from corredores.domain.models import PortfolioAssignment

    n = session.query(PortfolioAssignment).count()
    assert n == 0


def test_default_producer_optional(session, multi):
    org_id = multi["alfa"]["organization_id"]
    client_id = multi["alfa"]["party_id"]
    person = _person(session, org_id, "Prod", "Def")
    profile = create_producer_profile(session, organization_id=org_id, party_id=person.id)
    party = set_default_producer(
        session,
        organization_id=org_id,
        party_id=client_id,
        producer_profile_id=profile.id,
    )
    assert party.default_producer_profile_id == profile.id
    # Clearing does not touch policies
    set_default_producer(
        session, organization_id=org_id, party_id=client_id, producer_profile_id=None
    )
    assert session.get(Party, client_id).default_producer_profile_id is None


def test_canonical_role_codes_documented():
    assert PRODUCER in CANONICAL_ROLE_CODES
    assert "OWNER" in CANONICAL_ROLE_CODES
    assert "ADMIN" in CANONICAL_ROLE_CODES
