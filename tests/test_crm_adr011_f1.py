"""ADR-011 F1 — CRM domain schema + catalog seed + core invariants."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.crm_constants import (
    ACTIVITY_CALL,
    ACTIVITY_PENDING,
    DEFAULT_LEAD_SOURCES,
    DEFAULT_LOST_REASONS,
    PIPELINE_STAGE_CODES,
    PROSPECT_PERSON,
    STAGE_NEW,
    STAGE_WON,
)
from corredores.domain.models import (
    CrmActivity,
    CrmLeadSource,
    CrmLostReason,
    CrmOpportunity,
    CrmPipelineStage,
    CrmProspect,
    Organization,
    Party,
    RenewalOpportunity,
)
from corredores.services.crm_catalog_seed import ensure_default_crm_catalogs
from corredores.services.seed_pilot import seed_pilot


def setup_module():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as session:
        seed_pilot(session)
        session.commit()


def _org(session) -> Organization:
    org = session.query(Organization).order_by(Organization.created_at).first()
    assert org is not None
    return org


def test_catalog_seed_idempotent():
    with db.SessionLocal() as session:
        org = _org(session)
        a = ensure_default_crm_catalogs(session, org.id)
        session.commit()
        b = ensure_default_crm_catalogs(session, org.id)
        session.commit()
        assert a["pipeline_stages"] >= 0
        assert b == {"lead_sources": 0, "lost_reasons": 0, "pipeline_stages": 0}
        n_src = session.query(CrmLeadSource).filter_by(organization_id=org.id).count()
        n_lost = session.query(CrmLostReason).filter_by(organization_id=org.id).count()
        n_stages = session.query(CrmPipelineStage).filter_by(organization_id=org.id).count()
        assert n_src == len(DEFAULT_LEAD_SOURCES)
        assert n_lost == len(DEFAULT_LOST_REASONS)
        assert n_stages == len(PIPELINE_STAGE_CODES)
        won = (
            session.query(CrmPipelineStage)
            .filter_by(organization_id=org.id, code=STAGE_WON)
            .one()
        )
        assert won.is_won is True
        assert won.is_kanban is True


def test_prospect_not_customer_and_survives_conversion_link():
    with db.SessionLocal() as session:
        org = _org(session)
        ensure_default_crm_catalogs(session, org.id)
        src = (
            session.query(CrmLeadSource)
            .filter_by(organization_id=org.id, code="REFERRAL")
            .one()
        )
        referrer = Party(
            organization_id=org.id,
            party_type="PERSON",
            first_name="María",
            last_name="González",
            email="maria.ref@example.com",
        )
        session.add(referrer)
        session.flush()
        prospect = CrmProspect(
            organization_id=org.id,
            prospect_type=PROSPECT_PERSON,
            first_name="Juan",
            last_name="Pérez",
            phone="6000-0000",
            source_id=src.id,
            referral_source_id=referrer.id,
            status="OPEN",
            created_by="test",
        )
        session.add(prospect)
        session.flush()
        customer = Party(
            organization_id=org.id,
            party_type="PERSON",
            first_name="Juan",
            last_name="Pérez",
            phone="6000-0000",
        )
        session.add(customer)
        session.flush()
        prospect.converted_customer_id = customer.id
        prospect.status = "CONVERTED"
        session.flush()
        session.commit()
        again = session.get(CrmProspect, prospect.id)
        assert again is not None
        assert again.converted_customer_id == customer.id
        assert again.referral_source_id == referrer.id


def test_one_prospect_multiple_opportunities():
    with db.SessionLocal() as session:
        org = _org(session)
        ensure_default_crm_catalogs(session, org.id)
        stage = (
            session.query(CrmPipelineStage)
            .filter_by(organization_id=org.id, code=STAGE_NEW)
            .one()
        )
        p = CrmProspect(
            organization_id=org.id,
            prospect_type=PROSPECT_PERSON,
            first_name="Juan",
            last_name="Pérez",
            email="juan@example.com",
        )
        session.add(p)
        session.flush()
        o1 = CrmOpportunity(
            organization_id=org.id,
            prospect_id=p.id,
            title="Auto Juan Pérez",
            stage_id=stage.id,
            stage_code=STAGE_NEW,
            estimated_premium=Decimal("620.00"),
        )
        o2 = CrmOpportunity(
            organization_id=org.id,
            prospect_id=p.id,
            title="Vida Juan Pérez",
            stage_id=stage.id,
            stage_code=STAGE_NEW,
            estimated_premium=Decimal("180.00"),
        )
        session.add_all([o1, o2])
        session.commit()
        n = session.query(CrmOpportunity).filter_by(prospect_id=p.id).count()
        assert n == 2


def test_opportunity_for_existing_customer_without_prospect():
    with db.SessionLocal() as session:
        org = _org(session)
        ensure_default_crm_catalogs(session, org.id)
        customer = Party(
            organization_id=org.id,
            party_type="PERSON",
            first_name="Ana",
            last_name="Cliente",
        )
        session.add(customer)
        session.flush()
        opp = CrmOpportunity(
            organization_id=org.id,
            customer_id=customer.id,
            title="Vida Ana Cliente",
            stage_code=STAGE_NEW,
            product_interest="VIDA",
        )
        session.add(opp)
        session.commit()
        assert opp.prospect_id is None
        assert opp.customer_id == customer.id


def test_opportunity_requires_prospect_or_customer():
    with db.SessionLocal() as session:
        org = _org(session)
        opp = CrmOpportunity(
            organization_id=org.id,
            title="Huérfana",
            stage_code=STAGE_NEW,
        )
        session.add(opp)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_crm_activity_on_opportunity():
    with db.SessionLocal() as session:
        org = _org(session)
        p = CrmProspect(
            organization_id=org.id,
            first_name="Luis",
            mobile="6111-1111",
        )
        session.add(p)
        session.flush()
        opp = CrmOpportunity(
            organization_id=org.id,
            prospect_id=p.id,
            title="Auto Luis",
            stage_code=STAGE_NEW,
        )
        session.add(opp)
        session.flush()
        due = datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc)
        act = CrmActivity(
            organization_id=org.id,
            opportunity_id=opp.id,
            prospect_id=p.id,
            activity_type=ACTIVITY_CALL,
            title="Llamar hoy 3:00 PM",
            due_at=due,
            status=ACTIVITY_PENDING,
            assignee_subject_id="piloto:producer-a",
        )
        session.add(act)
        opp.next_activity_at = due
        session.commit()
        assert session.get(CrmActivity, act.id).status == ACTIVITY_PENDING
        assert session.get(CrmOpportunity, opp.id).next_activity_at == due


def test_renewal_opportunity_untouched():
    """ADR-011 must not overload renewal_opportunities."""
    assert CrmOpportunity.__tablename__ == "crm_opportunities"
    assert RenewalOpportunity.__tablename__ == "renewal_opportunities"
    assert CrmOpportunity.__tablename__ != RenewalOpportunity.__tablename__
