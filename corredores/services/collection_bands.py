"""Cobranza banding — maps Domain Truth to UX bands (not a second ledger)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from corredores.domain.enums import CollectionBand, PaymentPromiseStatus
from corredores.domain.models import Installment, PaymentPromise
from corredores.services.installment_status import (
    DerivedInstallmentStatus,
    derive_installment_status,
    outstanding_balance,
)


def classify_collection_band(
    installment: Installment,
    *,
    active_promise: PaymentPromise | None = None,
    broken_promise: PaymentPromise | None = None,
    has_exception: bool = False,
    today: date | None = None,
) -> CollectionBand:
    today = today or date.today()
    if has_exception:
        return CollectionBand.EXCEPTION
    # Promesa activa vigente gana sobre una incumplida vieja (re-promesa).
    if active_promise and active_promise.status == PaymentPromiseStatus.ACTIVE:
        if promise_is_broken(active_promise, today=today):
            return CollectionBand.BROKEN_PROMISE
        return CollectionBand.PROMISE
    if broken_promise and (
        broken_promise.status == PaymentPromiseStatus.BROKEN
        or promise_is_broken(broken_promise, today=today)
    ):
        return CollectionBand.BROKEN_PROMISE

    status = derive_installment_status(installment, today)
    balance = outstanding_balance(installment)

    if status == DerivedInstallmentStatus.CANCELLED:
        return CollectionBand.AUTOMATIC
    if status == DerivedInstallmentStatus.PAID or balance <= 0:
        return CollectionBand.AUTOMATIC
    if status in (DerivedInstallmentStatus.OVERDUE, DerivedInstallmentStatus.DUE):
        return CollectionBand.INTERVENTION
    if status == DerivedInstallmentStatus.PARTIALLY_PAID:
        return CollectionBand.INTERVENTION
    # PENDING future
    return CollectionBand.AUTOMATIC


def promise_is_broken(promise: PaymentPromise, *, today: date | None = None) -> bool:
    today = today or date.today()
    if promise.status == PaymentPromiseStatus.BROKEN:
        return True
    if promise.status == PaymentPromiseStatus.ACTIVE and promise.promised_date < today:
        return True
    return False
