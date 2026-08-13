"""Payments package — SaaS checkout (ADR-006) + cobranza de primas (record_payment)."""

from corredores.services.payments.premium import record_payment
from corredores.services.payments.service import PaymentResult, PaymentService

__all__ = ["PaymentService", "PaymentResult", "record_payment"]
