"""Seed catalog lines, carriers stub, and pilot CommissionRule/Split (D-06).

Rates mirror Excel formula catalog — not personal data.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.enums import CalculationBase
from corredores.domain.models import (
    Carrier,
    CommissionRule,
    CommissionSplitRule,
    InsuranceLine,
    Organization,
)
from corredores.services.auto_e2e import ensure_auto_line


LINES = [
    ("AUTO", "Automóvil", True),
    ("MOTO", "Moto", False),
    ("HOGAR", "Multirriesgo residencial", False),
    ("COMERCIAL", "Multirriesgo comercial", False),
    ("RC", "Responsabilidad civil", False),
    ("INCENDIO", "Incendio y aliadas", False),
    ("TRANSPORTE", "Transporte", False),
    ("VIDA", "Vida individual", False),
    ("SALUD", "Salud individual", False),
    ("AP", "Accidentes personales", False),
]

# Line-level rates from Emisiones.xlsx formulas (piloto histórico).
LINE_RATES: dict[str, Decimal] = {
    "AUTO": Decimal("0.20"),
    "MOTO": Decimal("0.20"),
    "AP": Decimal("0.20"),
    "HOGAR": Decimal("0.20"),
    "INCENDIO": Decimal("0.25"),
    "SALUD": Decimal("0.10"),
    "TRANSPORTE": Decimal("0.15"),
    "VIDA": Decimal("0.35"),
}

CARRIERS = [
    ("ANCON", "ANCÓN"),
    ("SURA", "SURA"),
    ("FEDPA", "FEDPA"),
    ("ASSA", "ASSA"),
    ("MAPFRE", "MAPFRE"),
]


def seed_pilot(session: Session, *, org_name: str = "ESecureBroker") -> dict:
    org = session.query(Organization).filter_by(name=org_name).one_or_none()
    if org is None:
        legacy = session.query(Organization).filter_by(name="Piloto Corredores").one_or_none()
        if legacy is not None:
            legacy.name = org_name
            org = legacy
        else:
            org = Organization(name=org_name)
            session.add(org)
            session.flush()

    ensure_auto_line(session)
    lines_n = 0
    for code, name, p0 in LINES:
        row = session.query(InsuranceLine).filter_by(code=code).one_or_none()
        if row is None:
            session.add(InsuranceLine(code=code, name=name, operational_in_p0=p0))
            lines_n += 1
        else:
            row.name = name
            row.operational_in_p0 = p0

    carriers_n = 0
    for code, name in CARRIERS:
        row = (
            session.query(Carrier)
            .filter_by(organization_id=org.id, code=code)
            .one_or_none()
        )
        if row is None:
            session.add(Carrier(organization_id=org.id, code=code, name=name))
            carriers_n += 1

    session.flush()

    rules_n = 0
    valid_from = date(2026, 1, 1)
    for code, rate in LINE_RATES.items():
        line = session.query(InsuranceLine).filter_by(code=code).one()
        existing = (
            session.query(CommissionRule)
            .filter_by(
                organization_id=org.id,
                insurance_line_id=line.id,
                agreement_reference="PILOTO_EXCEL_FORMULA_V1",
            )
            .one_or_none()
        )
        if existing is None:
            session.add(
                CommissionRule(
                    organization_id=org.id,
                    carrier_id=None,
                    insurance_line_id=line.id,
                    rate=rate,
                    calculation_base=CalculationBase.ANNUAL_PREMIUM,
                    valid_from=valid_from,
                    agreement_reference="PILOTO_EXCEL_FORMULA_V1",
                    source="SEED",
                )
            )
            rules_n += 1

    split = (
        session.query(CommissionSplitRule)
        .filter_by(organization_id=org.id, name="Piloto 70/30 Agente-Oficina")
        .one_or_none()
    )
    if split is None:
        session.add(
            CommissionSplitRule(
                organization_id=org.id,
                name="Piloto 70/30 Agente-Oficina",
                broker_share=Decimal("0.70"),
                office_share=Decimal("0.30"),
                executive_share=Decimal("0"),
                referral_share=Decimal("0"),
                valid_from=valid_from,
            )
        )
        split_created = 1
    else:
        split_created = 0

    session.flush()
    return {
        "organization_id": org.id,
        "lines_created": lines_n,
        "carriers_created": carriers_n,
        "commission_rules_created": rules_n,
        "split_rules_created": split_created,
    }
