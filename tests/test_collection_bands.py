from datetime import date, timedelta
from decimal import Decimal

from corredores.domain.enums import CollectionBand, PaymentPromiseStatus
from corredores.domain.models import Installment, PaymentPromise
from corredores.services.collection_bands import classify_collection_band, promise_is_broken


def _inst(due: date, amount: str = "100") -> Installment:
    return Installment(
        payment_plan_id="p",
        installment_number=1,
        due_date=due,
        amount=Decimal(amount),
        due_date_source="MANUAL",
        allocations=[],
    )


def test_overdue_is_intervention():
    today = date(2026, 8, 10)
    band = classify_collection_band(_inst(today - timedelta(days=2)), today=today)
    assert band == CollectionBand.INTERVENTION


def test_active_promise_band():
    today = date(2026, 8, 10)
    promise = PaymentPromise(
        organization_id="o",
        policy_id="pol",
        promised_amount=Decimal("100"),
        promised_date=today + timedelta(days=3),
        status=PaymentPromiseStatus.ACTIVE,
    )
    band = classify_collection_band(_inst(today - timedelta(days=2)), active_promise=promise, today=today)
    assert band == CollectionBand.PROMISE


def test_broken_promise_detection():
    today = date(2026, 8, 10)
    promise = PaymentPromise(
        organization_id="o",
        policy_id="pol",
        promised_amount=Decimal("100"),
        promised_date=today - timedelta(days=1),
        status=PaymentPromiseStatus.ACTIVE,
    )
    assert promise_is_broken(promise, today=today) is True
