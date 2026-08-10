from datetime import date, timedelta
from decimal import Decimal

from corredores.db import Base, SessionLocal, engine
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.enums import PaymentPromiseStatus
from corredores.services.auto_e2e import run_auto_e2e_demo
from corredores.services.promises import break_promise, create_promise, fulfill_promise
from corredores.services.today import build_today_queue


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_promise_fulfill_and_today_queue():
    today = date(2026, 8, 10)
    with SessionLocal() as session:
        result = run_auto_e2e_demo(session, today=today)
        # second installment still pending — create promise
        inst2 = result.installment_ids[1]
        promise = create_promise(
            session,
            organization_id=result.organization_id,
            policy_id=result.policy_id,
            installment_id=inst2,
            promised_amount=Decimal("100"),
            promised_date=today + timedelta(days=5),
            actor_id="tester",
        )
        assert promise.status == PaymentPromiseStatus.ACTIVE
        queue = build_today_queue(
            session, result.organization_id, today=today, renewal_horizon_days=400
        )
        assert any(w.type == "COLLECTION" for w in queue)
        assert any(w.type == "RENEWAL" for w in queue)
        fulfill_promise(session, promise, actor_id="tester")
        assert promise.status == PaymentPromiseStatus.FULFILLED
        session.commit()


def test_break_promise():
    today = date(2026, 8, 10)
    with SessionLocal() as session:
        result = run_auto_e2e_demo(session, today=today)
        promise = create_promise(
            session,
            organization_id=result.organization_id,
            policy_id=result.policy_id,
            installment_id=result.installment_ids[2],
            promised_amount=Decimal("50"),
            promised_date=today + timedelta(days=1),
        )
        break_promise(session, promise)
        assert promise.status == PaymentPromiseStatus.BROKEN
        session.commit()
