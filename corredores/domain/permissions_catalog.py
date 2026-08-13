"""Canonical permission catalog + system role matrix (ADR-008 F7).

System roles are immutable in semantics. Custom org roles pull from this catalog.
"""

from __future__ import annotations

from corredores.domain.membership_roles import (
    ADMIN,
    BROKER,
    COLLECTIONS,
    OWNER,
    PLATFORM,
    PRODUCER,
)

# --- Catalog (resource:operation) ---
PERMISSION_CATALOG: tuple[str, ...] = (
    "me:read",
    "organizations:list",
    "organizations:select",
    "today:read",
    "customers:list",
    "customers:search",
    "customers:read",
    "customers:360",
    "customers:create",
    "customers:update",
    "policies:list",
    "policies:read",
    "policies:create",
    "policies:update",
    "collections:read",
    "collections:create",
    "collections:update",
    "collections:manage",
    "renewals:read",
    "renewals:create",
    "renewals:update",
    "renewals:manage",
    "claims:read",
    "claims:create",
    "claims:update",
    "claims:manage",
    "documents:read",
    "documents:manage",
    "activities:read",
    "activities:create",
    "activities:update",
    "producers:read",
    "producers:manage",
    "reports:read",
    "members:read",
    "members:manage",
    "roles:read",
    "roles:manage",
    "incentives:read",
    "incentives:manage",
    "crm:read",
    "crm:manage",
    "settings:read",
    "settings:manage",
    "platform:admin",
)

PERMISSION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Clientes", ("customers:list", "customers:search", "customers:read", "customers:360", "customers:create", "customers:update")),
    ("Pólizas", ("policies:list", "policies:read", "policies:create", "policies:update")),
    ("Cobranza", ("collections:read", "collections:create", "collections:update", "collections:manage")),
    ("Renovaciones", ("renewals:read", "renewals:create", "renewals:update", "renewals:manage")),
    ("Reclamos", ("claims:read", "claims:create", "claims:update", "claims:manage")),
    ("Documentos", ("documents:read", "documents:manage")),
    ("Gestiones", ("activities:read", "activities:create", "activities:update")),
    ("Productores", ("producers:read", "producers:manage")),
    ("Reportes", ("reports:read",)),
    ("CRM", ("crm:read", "crm:manage")),
    (
        "Administración",
        (
            "members:read",
            "members:manage",
            "roles:read",
            "roles:manage",
            "incentives:read",
            "incentives:manage",
            "settings:read",
            "settings:manage",
        ),
    ),
)

_READ_CORE = (
    "me:read",
    "organizations:list",
    "organizations:select",
    "today:read",
    "customers:list",
    "customers:search",
    "customers:read",
    "customers:360",
    "policies:list",
    "policies:read",
)

_WRITE_CORE = (
    "customers:create",
    "customers:update",
    "policies:create",
    "policies:update",
)

# System role → permissions (immutable contract for ESB GO)
SYSTEM_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    OWNER: _READ_CORE
    + _WRITE_CORE
    + (
        "collections:read",
        "collections:create",
        "collections:update",
        "collections:manage",
        "renewals:read",
        "renewals:create",
        "renewals:update",
        "renewals:manage",
        "claims:read",
        "claims:create",
        "claims:update",
        "claims:manage",
        "documents:read",
        "documents:manage",
        "activities:read",
        "activities:create",
        "activities:update",
        "producers:read",
        "producers:manage",
        "reports:read",
        "members:read",
        "members:manage",
        "roles:read",
        "roles:manage",
        "incentives:read",
        "incentives:manage",
        "crm:read",
        "crm:manage",
        "settings:read",
        "settings:manage",
    ),
    ADMIN: _READ_CORE
    + _WRITE_CORE
    + (
        "collections:read",
        "collections:create",
        "collections:update",
        "collections:manage",
        "renewals:read",
        "renewals:create",
        "renewals:update",
        "renewals:manage",
        "claims:read",
        "claims:create",
        "claims:update",
        "claims:manage",
        "documents:read",
        "documents:manage",
        "activities:read",
        "activities:create",
        "activities:update",
        "producers:read",
        "producers:manage",
        "reports:read",
        "members:read",
        "members:manage",
        "roles:read",
        "roles:manage",  # custom roles only — enforced in service
        "incentives:read",
        "incentives:manage",
        "crm:read",
        "crm:manage",
        "settings:read",
        "settings:manage",
    ),
    BROKER: _READ_CORE
    + _WRITE_CORE
    + (
        "collections:read",
        "renewals:read",
        "renewals:update",
        "claims:read",
        "claims:update",
        "documents:read",
        "documents:manage",
        "activities:read",
        "activities:create",
        "activities:update",
        "reports:read",
        "incentives:read",
        "crm:read",
        "crm:manage",
        "settings:read",
    ),
    COLLECTIONS: _READ_CORE
    + (
        "collections:read",
        "collections:create",
        "collections:update",
        "collections:manage",
        "renewals:read",
        "claims:read",
        "documents:read",
        "activities:read",
        "activities:create",
        "reports:read",
        "incentives:read",
        "crm:read",
    ),
    PRODUCER: _READ_CORE
    + _WRITE_CORE
    + (
        "collections:read",
        "renewals:read",
        "renewals:update",
        "claims:read",
        "claims:update",
        "documents:read",
        "documents:manage",
        "activities:read",
        "activities:create",
        "activities:update",
        "reports:read",
        "incentives:read",
        "crm:read",
        "crm:manage",
    ),
    PLATFORM: _READ_CORE
    + (
        "platform:admin",
        "producers:read",
        "producers:manage",
        "reports:read",
        "members:read",
        "members:manage",
        "roles:read",
        "roles:manage",
        "incentives:read",
        "incentives:manage",
        "crm:read",
        "crm:manage",
        "settings:read",
        "settings:manage",
    ),
}

SYSTEM_ROLE_LABELS: dict[str, str] = {
    OWNER: "Propietario",
    ADMIN: "Administrador",
    BROKER: "Corredor",
    PRODUCER: "Productor",
    COLLECTIONS: "Cobranza",
    PLATFORM: "Plataforma",
}

# Permissions forbidden on custom roles
CUSTOM_ROLE_FORBIDDEN: frozenset[str] = frozenset({"platform:admin"})


def is_known_permission(code: str) -> bool:
    return code in PERMISSION_CATALOG
