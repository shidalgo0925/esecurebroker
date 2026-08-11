"""Catálogo de planes SaaS ESecureBroker — modelo operativo (PLANES_COMERCIALES_V1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from corredores.config import settings


@dataclass(frozen=True)
class SaasPlan:
    code: str
    name: str
    price_monthly_usd: int | None  # None = a medida / Enterprise
    tagline: str
    features: tuple[str, ...]
    audience: str
    seats_included: int | None
    highlighted: bool = False
    cta: str = "Comenzar"
    contact_sales: bool = False


# Códigos: individual | oficina | broker_red | enterprise
PLANS: dict[str, SaasPlan] = {
    "individual": SaasPlan(
        code="individual",
        name="Individual",
        price_monthly_usd=55,
        audience="Trabajo por mi cuenta",
        seats_included=1,
        tagline="Corredor independiente: todo el ciclo operativo, un solo usuario.",
        features=(
            "1 licencia (1 corredor)",
            "Clientes, pólizas y cartera",
            "Cobranza de primas y renovaciones",
            "Pendientes, documentos y reclamos",
            "Vista Hoy y reportes básicos",
        ),
        cta="Comenzar Individual",
    ),
    "oficina": SaasPlan(
        code="oficina",
        name="Oficina",
        price_monthly_usd=99,
        audience="Trabajo con mi equipo",
        seats_included=15,
        tagline="Correduría pequeña/mediana: el equipo interno sobre la misma cartera.",
        features=(
            "Hasta 15 licencias de usuario",
            "Roles, asignaciones y actividad",
            "Todo el ciclo de Individual",
            "Reportes de oficina",
            "Sin licencias ilimitadas",
        ),
        highlighted=True,
        cta="Comenzar Oficina",
    ),
    "broker_red": SaasPlan(
        code="broker_red",
        name="Broker / Red",
        price_monthly_usd=159,
        audience="Administro agentes",
        seats_included=15,
        tagline="Broker que administra agentes: consolidación y cartera por productor.",
        features=(
            "Hasta 15 licencias de oficina (equipo interno)",
            "Agentes / productores aparte (no consumen esas 15)",
            "Jerarquía, cartera y producción por agente",
            "Comisiones de red y supervisión",
            "Todo el ciclo operativo de Oficina",
        ),
        cta="Comenzar Broker / Red",
    ),
    "enterprise": SaasPlan(
        code="enterprise",
        name="Enterprise",
        price_monthly_usd=None,
        audience="Grupo o operación a escala",
        seats_included=None,
        tagline="Redes grandes, multi-organización, SLA y acompañamiento dedicado.",
        features=(
            "Todo lo de Broker / Red",
            "Multi-organización / holding",
            "Integraciones y onboarding dedicado",
            "SLA y soporte prioritario",
            "Condiciones y asientos a medida",
        ),
        cta="Hablar con ventas",
        contact_sales=True,
    ),
}

_PLAN_ALIASES: dict[str, str] = {
    "esencial": "individual",
    "profesional": "oficina",
}

DEFAULT_PLAN_CODE = "oficina"


def _canonical_code(code: str | None) -> str:
    raw = (code or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not raw:
        return DEFAULT_PLAN_CODE
    if raw in PLANS:
        return raw
    if raw in _PLAN_ALIASES:
        return _PLAN_ALIASES[raw]
    if raw in {"red", "broker", "brokerred"}:
        return "broker_red"
    if raw in {"enterprice", "empresarial"}:  # typo frecuente
        return "enterprise"
    return DEFAULT_PLAN_CODE


def get_plan(code: str | None) -> SaasPlan | None:
    if not code:
        return None
    return PLANS.get(_canonical_code(code))


def require_plan(code: str | None) -> SaasPlan:
    return get_plan(code) or PLANS[DEFAULT_PLAN_CODE]


def start_href(plan_code: str | None = None) -> str:
    """CTA de alta: URL EN1 si está configurada; si no, registro piloto local."""
    code = _canonical_code(plan_code)
    plan = PLANS[code]
    if plan.contact_sales:
        return "/#contacto"
    base = (settings.saas_onboarding_url or "").strip()
    if base:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}plan={code}&product=esecurebroker"
    return f"/registro?plan={code}"


def plans_for_landing() -> list[dict[str, Any]]:
    order = ("individual", "oficina", "broker_red", "enterprise")
    out: list[dict[str, Any]] = []
    for code in order:
        p = PLANS[code]
        if p.seats_included is not None:
            if p.code == "individual":
                seats = "1 licencia"
            elif p.code in {"oficina", "broker_red"}:
                seats = f"Hasta {p.seats_included} licencias"
            else:
                seats = f"{p.seats_included} licencia" + ("s" if p.seats_included != 1 else "")
        elif p.contact_sales:
            seats = "A medida"
        else:
            seats = "Según red"
        price_label = "A medida" if p.price_monthly_usd is None else f"${p.price_monthly_usd}"
        out.append(
            {
                "code": p.code,
                "name": p.name,
                "price": p.price_monthly_usd,
                "price_label": price_label,
                "price_suffix": "" if p.price_monthly_usd is None else " / mes",
                "tagline": p.tagline,
                "audience": p.audience,
                "seats_label": seats,
                "features": list(p.features),
                "highlighted": p.highlighted,
                "cta": p.cta,
                "contact_sales": p.contact_sales,
                "register_href": start_href(p.code),
            }
        )
    return out
