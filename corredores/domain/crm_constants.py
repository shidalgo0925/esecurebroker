"""ADR-011 — ESB CRM domain constants (F1).

Distinct from renewal CRM (`RenewalOpportunity`) and mobile Interaction “activities”.
UI may use Spanish labels; codes are stable English tokens.
"""

from __future__ import annotations

# --- Prospect ---
PROSPECT_PERSON = "PERSON"
PROSPECT_COMPANY = "COMPANY"
PROSPECT_TYPES: frozenset[str] = frozenset({PROSPECT_PERSON, PROSPECT_COMPANY})

PROSPECT_OPEN = "OPEN"
PROSPECT_QUALIFIED = "QUALIFIED"
PROSPECT_CONVERTED = "CONVERTED"
PROSPECT_ARCHIVED = "ARCHIVED"
PROSPECT_STATUSES: frozenset[str] = frozenset(
    {PROSPECT_OPEN, PROSPECT_QUALIFIED, PROSPECT_CONVERTED, PROSPECT_ARCHIVED}
)

# --- Pipeline stages (codes; Spanish labels for UI later) ---
STAGE_NEW = "NEW"
STAGE_CONTACTED = "CONTACTED"
STAGE_QUALIFIED = "QUALIFIED"
STAGE_QUOTING = "QUOTING"
STAGE_NEGOTIATION = "NEGOTIATION"
STAGE_WON = "WON"
STAGE_LOST = "LOST"

PIPELINE_STAGE_CODES: tuple[str, ...] = (
    STAGE_NEW,
    STAGE_CONTACTED,
    STAGE_QUALIFIED,
    STAGE_QUOTING,
    STAGE_NEGOTIATION,
    STAGE_WON,
    STAGE_LOST,
)

PIPELINE_STAGE_LABELS_ES: dict[str, str] = {
    STAGE_NEW: "Nuevo",
    STAGE_CONTACTED: "Contactado",
    STAGE_QUALIFIED: "Calificado",
    STAGE_QUOTING: "Cotizando",
    STAGE_NEGOTIATION: "Negociación",
    STAGE_WON: "Ganado",
    STAGE_LOST: "Perdido",
}

# Kanban columns (LOST consulted separately)
PIPELINE_KANBAN_CODES: tuple[str, ...] = (
    STAGE_NEW,
    STAGE_CONTACTED,
    STAGE_QUALIFIED,
    STAGE_QUOTING,
    STAGE_NEGOTIATION,
    STAGE_WON,
)

# --- Activity ---
ACTIVITY_CALL = "CALL"
ACTIVITY_WHATSAPP = "WHATSAPP"
ACTIVITY_EMAIL = "EMAIL"
ACTIVITY_REQUEST_DOCUMENT = "REQUEST_DOCUMENT"
ACTIVITY_PREPARE_QUOTE = "PREPARE_QUOTE"
ACTIVITY_MEETING = "MEETING"
ACTIVITY_FOLLOW_UP = "FOLLOW_UP"
ACTIVITY_CUSTOM = "CUSTOM"

ACTIVITY_TYPES: frozenset[str] = frozenset(
    {
        ACTIVITY_CALL,
        ACTIVITY_WHATSAPP,
        ACTIVITY_EMAIL,
        ACTIVITY_REQUEST_DOCUMENT,
        ACTIVITY_PREPARE_QUOTE,
        ACTIVITY_MEETING,
        ACTIVITY_FOLLOW_UP,
        ACTIVITY_CUSTOM,
    }
)

ACTIVITY_PENDING = "PENDING"
ACTIVITY_DONE = "DONE"
ACTIVITY_CANCELLED = "CANCELLED"
ACTIVITY_OVERDUE = "OVERDUE"  # derived/display; may also be stored after sweep

ACTIVITY_STATUSES: frozenset[str] = frozenset(
    {ACTIVITY_PENDING, ACTIVITY_DONE, ACTIVITY_CANCELLED, ACTIVITY_OVERDUE}
)

# --- Default lead sources (org catalog seed) ---
DEFAULT_LEAD_SOURCES: tuple[tuple[str, str], ...] = (
    ("REFERRAL", "Referido"),
    ("WEB", "Web"),
    ("WHATSAPP", "WhatsApp"),
    ("CALL", "Llamada"),
    ("VISIT", "Visita"),
    ("CAMPAIGN", "Campaña"),
    ("PRODUCER", "Productor"),
    ("EXISTING_CUSTOMER", "Cliente existente"),
    ("EVENT", "Evento"),
    ("SOCIAL", "Redes sociales"),
    ("OTHER", "Otro"),
)

# --- Default lost reasons ---
DEFAULT_LOST_REASONS: tuple[tuple[str, str], ...] = (
    ("PRICE", "Precio"),
    ("NO_RESPONSE", "Cliente no respondió"),
    ("OTHER_BROKER", "Eligió otra correduría"),
    ("NOT_QUALIFIED", "No calificó"),
    ("MISSING_DOCS", "No presentó documentos"),
    ("PRODUCT_UNAVAILABLE", "Producto no disponible"),
    ("TERMS", "Condiciones"),
    ("DUPLICATE", "Duplicado"),
    ("OTHER", "Otro"),
)
