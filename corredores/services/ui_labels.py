"""Etiquetas en español para códigos de dominio mostrados en UI."""

from __future__ import annotations

# Códigos de DB/API se mantienen en inglés; solo la presentación es ES.
LABELS_ES: dict[str, str] = {
    # Membresía / roles scope
    "INVITED": "Invitado",
    "ACTIVE": "Activo",
    "INACTIVE": "Inactivo",
    "REVOKED": "Revocado",
    "ORGANIZATION": "Organización",
    "ASSIGNED_PORTFOLIO": "Cartera asignada",
    "OWNER": "Propietario",
    "ADMIN": "Administrador",
    "BROKER": "Corredor",
    "PRODUCER": "Productor",
    "COLLECTIONS": "Cobranza",
    "PLATFORM": "Plataforma",
    # Suscripción SaaS
    "pending": "Pendiente",
    "active": "Activa",
    "past_due": "Vencida",
    "canceled": "Cancelada",
    "approved": "Aprobado",
    "rejected": "Rechazado",
    # Póliza
    "PENDING_EFFECTIVE": "Pendiente de vigencia",
    "EXPIRING": "Por vencer",
    "EXPIRED": "Vencida",
    "CANCELLATION_PENDING": "Cancelación pendiente",
    "CANCELLED": "Cancelada",
    # Renovación / CRM
    "UPCOMING": "Próxima",
    "CONTACT_PENDING": "Pendiente de contacto",
    "CONTACTED": "Contactado",
    "QUOTING": "Cotizando",
    "PROPOSAL_SENT": "Propuesta enviada",
    "WAITING_CLIENT": "Esperando cliente",
    "ACCEPTED": "Aceptada",
    "RENEWED": "Renovada",
    "DECLINED": "Rechazada",
    "LOST": "Perdida",
    "NON_RENEWED": "No renovada",
    # Reclamos
    "REPORTED": "Reportado",
    "DOCUMENTS_PENDING": "Documentos pendientes",
    "SUBMITTED": "Enviado",
    "UNDER_REVIEW": "En revisión",
    "ADJUSTER_ASSIGNED": "Ajustador asignado",
    "APPROVED": "Aprobado",
    "REJECTED": "Rechazado",
    "SETTLED": "Liquidado",
    "CLOSED": "Cerrado",
    # Promesas / cobranza
    "FULFILLED": "Cumplida",
    "BROKEN": "Incumplida",
    "AUTOMATIC": "Automático",
    "INTERVENTION": "Intervención",
    "PROMISE": "Promesa",
    "BROKEN_PROMISE": "Promesa incumplida",
    "EXCEPTION": "Excepción",
    # Incentivos cia
    "DRAFT": "Borrador",
    "CLOSED": "Cerrado",
    "COLLECTION": "Cobranza",
    "PRODUCTION": "Producción",
    "ANNUAL": "Anual",
    "CUSTOM": "Personalizado",
    "PERCENTAGE": "Porcentaje",
    "FIXED_AMOUNT": "Monto fijo",
    "PENDING": "Pendiente",
    "CONFIRMED": "Confirmado",
    "REVERSED": "Reversado",
    "ESTIMATED": "Estimado",
    "EARNED": "Devengado",
    "CALCULATED": "Calculado",
    "CLAIMED": "Reclamado",
    "RECOGNIZED": "Reconocido",
    "PAID": "Pagado",
    "DISPUTED": "En disputa",
    "PARTIALLY_PAID": "Parcialmente pagado",
    # Cotización / submission
    "ISSUING": "En emisión",
    "ISSUED": "Emitida",
    # Misc
    "MANUAL": "Manual",
    "FILE": "Archivo",
    "API": "API",
    "FULL_DIGITAL": "Digital completo",
    # Métodos de pago SaaS
    "transfer": "Transferencia",
    "yappy": "Yappy",
    "promo": "Promoción",
    "card": "Tarjeta",
    "bank_manual": "Transferencia manual",
}


def label_es(value: object, default: str | None = None) -> str:
    """Traduce un código de dominio a etiqueta española; si no hay mapa, deja el valor."""
    if value is None:
        return default if default is not None else "—"
    key = str(value).strip()
    if not key:
        return default if default is not None else "—"
    if key in LABELS_ES:
        return LABELS_ES[key]
    upper = key.upper()
    if upper in LABELS_ES:
        return LABELS_ES[upper]
    lower = key.lower()
    if lower in LABELS_ES:
        return LABELS_ES[lower]
    return default if default is not None else key
