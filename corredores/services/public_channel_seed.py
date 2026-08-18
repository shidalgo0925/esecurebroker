"""Seed public sales channel for an organization by name (no hardcoded org UUID)."""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.models import (
    CrmLeadSource,
    Organization,
    PublicPlanRate,
    PublicProductPlan,
    PublicSalesChannel,
)
from corredores.domain.public_channel_constants import REGION_CODES
from corredores.services.crm_catalog_seed import ensure_default_crm_catalogs

# DEV_PLACEHOLDER daily rates by plan — replace with official tariffs.
_PLACEHOLDER_PER_DAY = {
    "GLOBAL": Decimal("4.50"),
    "MAXIMUS": Decimal("6.75"),
    "SUPREME": Decimal("9.25"),
}

_PLAN_META = (
    (
        "GLOBAL",
        "Global",
        10,
        False,
        ["Asistencia médica", "Gastos de farmacia", "Repatriación"],
        {"asistencia_medica": "USD 30,000", "farmacia": "USD 500"},
    ),
    (
        "MAXIMUS",
        "Maximus",
        20,
        True,
        ["Asistencia médica ampliada", "Equipaje", "Cancelación de viaje"],
        {"asistencia_medica": "USD 60,000", "equipaje": "USD 1,500"},
    ),
    (
        "SUPREME",
        "Supreme",
        30,
        False,
        ["Asistencia médica superior", "Equipaje", "Cancelación", "Responsabilidad civil"],
        {"asistencia_medica": "USD 100,000", "rc": "USD 25,000"},
    ),
)


def ensure_public_channel_for_org_name(
    session: Session,
    *,
    organization_name: str = "Grupo Arsi",
    slug: str = "avioncito",
) -> PublicSalesChannel | None:
    org = (
        session.query(Organization)
        .filter(Organization.name == organization_name, Organization.active.is_(True))
        .one_or_none()
    )
    if org is None:
        return None
    ensure_default_crm_catalogs(session, org.id)
    web = (
        session.query(CrmLeadSource)
        .filter_by(organization_id=org.id, code="WEB", active=True)
        .one_or_none()
    )
    ch = session.query(PublicSalesChannel).filter_by(slug=slug).one_or_none()
    if ch is None:
        ch = PublicSalesChannel(
            slug=slug,
            organization_id=org.id,
            name=f"{organization_name} — Seguro de viaje",
            product_code="VIAJE",
            product_label="Seguro de viaje",
            origin_default="Panamá",
            origin_fixed=False,
            lead_source_id=web.id if web else None,
            currency="USD",
            branding_json=json.dumps(
                {
                    "display_name": organization_name,
                    "product_tagline": "Cotiza tu seguro de viaje",
                    "accent": "brass",
                    "visual": "esb-expediente",
                },
                ensure_ascii=False,
            ),
            active=True,
            notes="Seeded by name lookup. Visual: ESB expediente tokens (ink/paper/brass). Rates=DEV_PLACEHOLDER.",
        )
        session.add(ch)
        session.flush()
    else:
        ch.organization_id = org.id
        ch.active = True
        if web and not ch.lead_source_id:
            ch.lead_source_id = web.id
        session.flush()

    existing = {p.code: p for p in session.query(PublicProductPlan).filter_by(channel_id=ch.id)}
    for code, name, sort, highlight, coverages, limits in _PLAN_META:
        plan = existing.get(code)
        if plan is None:
            plan = PublicProductPlan(
                channel_id=ch.id,
                code=code,
                name=name,
                sort_order=sort,
                currency="USD",
                coverages_json=json.dumps(coverages, ensure_ascii=False),
                limits_json=json.dumps(limits, ensure_ascii=False),
                highlight=highlight,
                active=True,
            )
            session.add(plan)
            session.flush()
        per_day = _PLACEHOLDER_PER_DAY[code]
        for region in REGION_CODES:
            rate = (
                session.query(PublicPlanRate)
                .filter_by(plan_id=plan.id, destination_region=region, age_min=0, age_max=120)
                .one_or_none()
            )
            if rate is None:
                session.add(
                    PublicPlanRate(
                        plan_id=plan.id,
                        destination_region=region,
                        age_min=0,
                        age_max=120,
                        amount_per_passenger_per_day=per_day,
                        currency="USD",
                        active=True,
                        notes="DEV_PLACEHOLDER",
                    )
                )
    session.flush()
    return ch
