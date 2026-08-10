"""Derived installment operational status (D-19) — never a second source of truth."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from corredores.domain.models import Installment, PaymentAllocation


class DerivedInstallmentStatus(StrEnum):
    PENDING = "PENDING"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


def allocated_total(installment: Installment) -> Decimal:
    return sum((a.amount for a in installment.allocations), Decimal("0"))


def outstanding_balance(installment: Installment) -> Decimal:
    if installment.cancelled_at is not None:
        return Decimal("0")
    bal = installment.amount - allocated_total(installment)
    return bal if bal > 0 else Decimal("0")


def derive_installment_status(installment: Installment, today: date | None = None) -> DerivedInstallmentStatus:
    today = today or date.today()
    if installment.cancelled_at is not None:
        return DerivedInstallmentStatus.CANCELLED

    paid = allocated_total(installment)
    balance = installment.amount - paid

    if balance <= 0:
        return DerivedInstallmentStatus.PAID

    partial = paid > 0
    if installment.due_date > today:
        return DerivedInstallmentStatus.PARTIALLY_PAID if partial else DerivedInstallmentStatus.PENDING
    if installment.due_date == today:
        return DerivedInstallmentStatus.PARTIALLY_PAID if partial else DerivedInstallmentStatus.DUE
    # past due
    return DerivedInstallmentStatus.PARTIALLY_PAID if partial else DerivedInstallmentStatus.OVERDUE
