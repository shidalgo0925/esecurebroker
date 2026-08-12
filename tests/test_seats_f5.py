"""ADR-008 F5 — Seat limits enforcement."""

from __future__ import annotations

from datetime import date

import pytest

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.membership_roles import BROKER, OWNER, PRODUCER
from corredores.domain.models import OrgMembership, OrgSubscription, Party
from corredores.domain.enums import PartyType
from corredores.services.producer_portfolio import create_producer_profile
from corredores.services.seats import (
    SeatLimitError,
    activate_membership,
    extract_en1_seat_limits,
    grant_producer_system_access,
    persist_en1_seat_limits,
    seat_snapshot,
)
from corredores.services.seed_tenants import seed_multitenant_demo
from corredores.web.auth_session import actor_id_for_username


@pytest.fixture()
def session():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as s:
        yield s
        s.rollback()


def _reset_sub(session, org_id: str, plan_code: str) -> None:
    session.query(OrgMembership).filter_by(organization_id=org_id).delete()
    session.query(OrgSubscription).filter_by(organization_id=org_id).delete()
    session.add(
        OrgSubscription(
            organization_id=org_id,
            plan_code=plan_code,
            status="active",
            billing_provider="piloto",
        )
    )
    session.commit()


@pytest.fixture()
def org_individual(session):
    info = seed_multitenant_demo(session, today=date(2026, 8, 10))
    _reset_sub(session, info["alfa"]["organization_id"], "individual")
    return info


@pytest.fixture()
def org_broker(session):
    info = seed_multitenant_demo(session, today=date(2026, 8, 10))
    _reset_sub(session, info["alfa"]["organization_id"], "broker_red")
    return info


def test_extract_en1_compound_limits():
    assert extract_en1_seat_limits({"internal_seats": 10, "producer_seats": 5}) == (10, 5)
    assert extract_en1_seat_limits({"internal_seats": 3, "producer_seats": None}) == (3, None)
    assert extract_en1_seat_limits({"foo": 1}) is None


def test_individual_blocks_second_internal(session, org_individual):
    org = org_individual["alfa"]["organization_id"]
    activate_membership(
        session,
        subject_id=actor_id_for_username("owner1@ex.invalid"),
        organization_id=org,
        role_code=OWNER,
    )
    snap = seat_snapshot(session, org)
    assert snap.internal.limit == 1
    assert snap.internal.used == 1
    with pytest.raises(SeatLimitError):
        activate_membership(
            session,
            subject_id=actor_id_for_username("owner2@ex.invalid"),
            organization_id=org,
            role_code=BROKER,
        )


def test_individual_blocks_producer_access(session, org_individual):
    org = org_individual["alfa"]["organization_id"]
    person = Party(
        organization_id=org, party_type=PartyType.PERSON, first_name="P", last_name="One"
    )
    session.add(person)
    session.flush()
    profile = create_producer_profile(session, organization_id=org, party_id=person.id)
    with pytest.raises(SeatLimitError) as ei:
        grant_producer_system_access(
            session,
            organization_id=org,
            producer_profile_id=profile.id,
            subject_id=actor_id_for_username("prod@ex.invalid"),
        )
    assert "producer_seats" in str(ei.value)


def test_broker_red_allows_producer(session, org_broker):
    org = org_broker["alfa"]["organization_id"]
    person = Party(
        organization_id=org, party_type=PartyType.PERSON, first_name="Ana", last_name="Agente"
    )
    session.add(person)
    session.flush()
    profile = create_producer_profile(session, organization_id=org, party_id=person.id)
    mem = grant_producer_system_access(
        session,
        organization_id=org,
        producer_profile_id=profile.id,
        subject_id=actor_id_for_username("ana@ex.invalid"),
    )
    assert mem.role_code == PRODUCER
    snap = seat_snapshot(session, org)
    assert snap.producer.used == 1
    assert snap.producer.limit is None  # unlimited until EN1


def test_persist_en1_limits_used(session, org_individual):
    org = org_individual["alfa"]["organization_id"]
    sub = session.query(OrgSubscription).filter_by(organization_id=org).one()
    persist_en1_seat_limits(
        session, sub, {"internal_seats": 2, "producer_seats": 1}
    )
    snap = seat_snapshot(session, org)
    assert snap.source == "en1"
    assert snap.internal.limit == 2
    assert snap.producer.limit == 1
    activate_membership(
        session,
        subject_id=actor_id_for_username("a@ex.invalid"),
        organization_id=org,
        role_code=OWNER,
    )
    activate_membership(
        session,
        subject_id=actor_id_for_username("b@ex.invalid"),
        organization_id=org,
        role_code=BROKER,
    )
    with pytest.raises(SeatLimitError):
        activate_membership(
            session,
            subject_id=actor_id_for_username("c@ex.invalid"),
            organization_id=org,
            role_code=BROKER,
        )
