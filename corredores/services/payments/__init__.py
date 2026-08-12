"""PaymentService — orquestación de pago SaaS (ADR-006). Cobranza de primas vive aparte."""

from corredores.services.payments.service import PaymentResult, PaymentService

__all__ = ["PaymentService", "PaymentResult"]
