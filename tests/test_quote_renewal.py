from datetime import date
from decimal import Decimal

from corredores.db import Base, SessionLocal, engine
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.models import Carrier
from corredores.services.auto_e2e import ensure_auto_line, run_auto_e2e_demo
from corredores.services.quote_orchestrator import (
    CarrierQuoteStatus,
    QuoteResponseSource,
    build_comparator,
    create_quote_request,
    dispatch_carriers,
    record_api_quote_stub,
    record_file_quote,
    record_manual_quote,
)
from corredores.services.renewals import start_multi_carrier_recote, start_same_carrier_renewal


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_comparator_three_sources():
    today = date(2026, 8, 10)
    with SessionLocal() as session:
        result = run_auto_e2e_demo(session, today=today)
        auto = ensure_auto_line(session)
        c1 = session.query(Carrier).filter_by(organization_id=result.organization_id, code="DEMO").one()
        c2 = Carrier(organization_id=result.organization_id, code="ASSA", name="ASSA")
        c3 = Carrier(organization_id=result.organization_id, code="SURA", name="SURA")
        session.add_all([c2, c3])
        session.flush()

        qr = create_quote_request(
            session,
            organization_id=result.organization_id,
            insurance_line_id=auto.id,
            submission_id=result.submission_id,
            payload={"vehicle": "HILUX"},
        )
        cqrs = dispatch_carriers(session, qr, [c1.id, c2.id, c3.id])
        record_api_quote_stub(
            session, cqrs[0], organization_id=result.organization_id, premium=Decimal("500")
        )
        record_file_quote(
            session,
            cqrs[1],
            organization_id=result.organization_id,
            premium=Decimal("480"),
            file_ref="file:quotes/assa.pdf",
        )
        record_manual_quote(
            session, cqrs[2], organization_id=result.organization_id, premium=Decimal("510"), note="phone"
        )
        rows = build_comparator(session, qr.id)
        sources = {r.carrier_code: r.source for r in rows}
        assert sources["DEMO"] == QuoteResponseSource.API.value
        assert sources["ASSA"] == QuoteResponseSource.FILE.value
        assert sources["SURA"] == QuoteResponseSource.MANUAL.value
        assert all(r.premium is not None for r in rows)
        assert all(r.status == CarrierQuoteStatus.NORMALIZED for r in rows)
        session.commit()


def test_renewal_paths():
    today = date(2026, 8, 10)
    with SessionLocal() as session:
        result = run_auto_e2e_demo(session, today=today)
        from corredores.domain.models import RenewalOpportunity

        ren = session.query(RenewalOpportunity).filter_by(previous_policy_id=result.policy_id).first()
        assert ren is not None
        start_same_carrier_renewal(session, ren)
        assert ren.status == "CONTACTED"

        c2 = Carrier(organization_id=result.organization_id, code="FEDPA", name="FEDPA")
        session.add(c2)
        session.flush()
        demo = session.query(Carrier).filter_by(organization_id=result.organization_id, code="DEMO").one()
        ren2, qr, cqrs = start_multi_carrier_recote(
            session, ren, carrier_ids=[demo.id, c2.id]
        )
        assert ren2.status == "QUOTING"
        assert len(cqrs) == 2
        assert qr.id
        session.commit()
