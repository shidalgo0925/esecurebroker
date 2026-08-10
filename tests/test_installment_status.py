from datetime import date, timedelta
from decimal import Decimal

from corredores.domain.models import Installment, PaymentAllocation
from corredores.services.installment_status import DerivedInstallmentStatus, derive_installment_status


def _inst(due: date, amount: str = "100", cancelled=None, paid: str | None = None) -> Installment:
    inst = Installment(
        payment_plan_id="x",
        installment_number=1,
        due_date=due,
        amount=Decimal(amount),
        due_date_source="MANUAL",
        cancelled_at=cancelled,
    )
    inst.allocations = []
    if paid:
        inst.allocations = [
            PaymentAllocation(payment_id="p", installment_id="i", amount=Decimal(paid))
        ]
    return inst


def test_pending_future():
    today = date(2026, 8, 10)
    st = derive_installment_status(_inst(today + timedelta(days=5)), today)
    assert st == DerivedInstallmentStatus.PENDING


def test_due_today():
    today = date(2026, 8, 10)
    st = derive_installment_status(_inst(today), today)
    assert st == DerivedInstallmentStatus.DUE


def test_overdue():
    today = date(2026, 8, 10)
    st = derive_installment_status(_inst(today - timedelta(days=1)), today)
    assert st == DerivedInstallmentStatus.OVERDUE


def test_paid():
    today = date(2026, 8, 10)
    st = derive_installment_status(_inst(today - timedelta(days=1), paid="100"), today)
    assert st == DerivedInstallmentStatus.PAID


def test_partial_overdue():
    today = date(2026, 8, 10)
    st = derive_installment_status(_inst(today - timedelta(days=1), paid="40"), today)
    assert st == DerivedInstallmentStatus.PARTIALLY_PAID
