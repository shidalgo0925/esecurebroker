"""Seed catalog lines, carriers stub, and pilot CommissionRule/Split (D-06).

Rates mirror Excel formula catalog — formalized as PLAN_COMISIONES_V1.
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
from corredores.services.commission_plan import (
    BROKER_SHARE,
    BROKER_SHARE_EXEC,
    BROKER_SHARE_SOLO,
    EXECUTIVE_SHARE,
    EXECUTIVE_SHARE_EXEC,
    EXECUTIVE_SHARE_SOLO,
    LINE_LABELS,
    LINE_RATES,
    OFFICE_SHARE,
    OFFICE_SHARE_EXEC,
    OFFICE_SHARE_SOLO,
    PLAN_REF,
    REFERRAL_SHARE,
    REFERRAL_SHARE_EXEC,
    REFERRAL_SHARE_SOLO,
    SPLIT_REF,
    SPLIT_REF_EXEC,
    SPLIT_REF_SOLO,
)


LINES = [
    ("AUTO", "Automóvil", True),
    ("MOTO", "Moto", False),
    ("HOGAR", "Multirriesgo residencial", False),
    ("COMERCIAL", "Multirriesgo comercial", False),
    ("RC", "Responsabilidad civil", False),
    ("INCENDIO", "Incendio y aliadas", False),
    # Ramos técnicos (Aliado CAR / montaje / equipo)
    ("CAR", "Todo Riesgo Contratista", False),
    ("EAR", "Todo Riesgo Montaje", False),
    ("EQUIPO", "Equipo de contratistas", False),
    ("VIAJE", "Seguro de viaje", False),
    ("TRANSPORTE", "Transporte", False),
    ("VIDA", "Vida individual", False),
    ("SALUD", "Salud individual", False),
    ("AP", "Accidentes personales", False),
]

# Catálogo piloto = Tablas.xlsx · hoja Tabla · columna Aseguradoras (únicos).
CARRIERS = [
    ("ACERTA", "ACERTA"),
    ("ANCON", "ANCÓN"),
    ("ASSA", "ASSA"),
    ("FEDPA", "FEDPA"),
    ("IS", "IS"),
    ("MAPFRE", "MAPFRE"),
    ("SURA", "SURA"),
    ("VIVIR", "VIVIR"),
    ("PALIG", "PALIG"),
    ("REGIONAL", "REGIONAL"),
    ("ALIADO", "ALIADO"),
    ("BANESCO", "BANESCO"),
    ("BUPA", "BUPA"),
    ("CHUBB", "CHUBB"),
    ("FLORESTA", "FLORESTA"),
    ("GENERAL", "GENERAL"),
    ("GLOBAL", "GLOBAL"),
    ("MERCANTIL", "MERCANTIL"),
    ("MULTIBANK", "MULTIBANK"),
    ("NACIONAL", "NACIONAL"),
    ("OPTIMA", "OPTIMA"),
    ("SAGICOR", "SAGICOR"),
    ("WORLDWIDE", "WORLDWIDE"),
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
        line = session.query(InsuranceLine).filter_by(code=code).one_or_none()
        if line is None:
            session.add(
                InsuranceLine(
                    code=code,
                    name=LINE_LABELS.get(code, code),
                    operational_in_p0=(code == "AUTO"),
                )
            )
            session.flush()
            line = session.query(InsuranceLine).filter_by(code=code).one()
        existing = (
            session.query(CommissionRule)
            .filter_by(
                organization_id=org.id,
                insurance_line_id=line.id,
                agreement_reference=PLAN_REF,
                carrier_id=None,
            )
            .one_or_none()
        )
        if existing is None:
            legacy = (
                session.query(CommissionRule)
                .filter_by(
                    organization_id=org.id,
                    insurance_line_id=line.id,
                    agreement_reference="PILOTO_EXCEL_FORMULA_V1",
                    carrier_id=None,
                )
                .one_or_none()
            )
            if legacy is not None:
                legacy.agreement_reference = PLAN_REF
                legacy.rate = rate
                legacy.calculation_base = CalculationBase.ANNUAL_PREMIUM
            else:
                session.add(
                    CommissionRule(
                        organization_id=org.id,
                        carrier_id=None,
                        insurance_line_id=line.id,
                        rate=rate,
                        calculation_base=CalculationBase.ANNUAL_PREMIUM,
                        valid_from=valid_from,
                        agreement_reference=PLAN_REF,
                        source="SEED",
                    )
                )
                rules_n += 1
        else:
            existing.rate = rate
            existing.calculation_base = CalculationBase.ANNUAL_PREMIUM

    # Variante sin ejecutivo (histórica / fallback documental).
    solo = (
        session.query(CommissionSplitRule)
        .filter_by(organization_id=org.id, name=SPLIT_REF_SOLO)
        .one_or_none()
    )
    if solo is None:
        legacy_solo = (
            session.query(CommissionSplitRule)
            .filter(
                CommissionSplitRule.organization_id == org.id,
                CommissionSplitRule.name.in_(
                    [
                        "Piloto 70/30 Agente-Oficina",
                        "PLAN_CORREDORES_V1 — 70/30 Agente-Oficina",
                    ]
                ),
            )
            .order_by(CommissionSplitRule.valid_from.desc())
            .first()
        )
        if legacy_solo is not None and legacy_solo.name != SPLIT_REF:
            legacy_solo.name = SPLIT_REF_SOLO
            legacy_solo.broker_share = BROKER_SHARE_SOLO
            legacy_solo.office_share = OFFICE_SHARE_SOLO
            legacy_solo.executive_share = EXECUTIVE_SHARE_SOLO
            legacy_solo.referral_share = REFERRAL_SHARE_SOLO
        else:
            session.add(
                CommissionSplitRule(
                    organization_id=org.id,
                    name=SPLIT_REF_SOLO,
                    broker_share=BROKER_SHARE_SOLO,
                    office_share=OFFICE_SHARE_SOLO,
                    executive_share=EXECUTIVE_SHARE_SOLO,
                    referral_share=REFERRAL_SHARE_SOLO,
                    valid_from=date(2024, 1, 1),
                )
            )
    else:
        solo.broker_share = BROKER_SHARE_SOLO
        solo.office_share = OFFICE_SHARE_SOLO
        solo.executive_share = EXECUTIVE_SHARE_SOLO
        solo.referral_share = REFERRAL_SHARE_SOLO

    # Plan ejecutivos V1 — variante sin referido.
    exec_split = (
        session.query(CommissionSplitRule)
        .filter_by(organization_id=org.id, name=SPLIT_REF_EXEC)
        .one_or_none()
    )
    if exec_split is None:
        # Nombre histórico cuando SPLIT_REF era el plan ejecutivos.
        legacy_exec = (
            session.query(CommissionSplitRule)
            .filter_by(
                organization_id=org.id,
                name="PLAN_EJECUTIVOS_V1 — 60/10/30 Agente-Ejecutivo-Oficina",
            )
            .one_or_none()
        )
        if legacy_exec is not None:
            legacy_exec.name = SPLIT_REF_EXEC
            legacy_exec.broker_share = BROKER_SHARE_EXEC
            legacy_exec.office_share = OFFICE_SHARE_EXEC
            legacy_exec.executive_share = EXECUTIVE_SHARE_EXEC
            legacy_exec.referral_share = REFERRAL_SHARE_EXEC
            legacy_exec.valid_from = date(2026, 8, 11)
        else:
            session.add(
                CommissionSplitRule(
                    organization_id=org.id,
                    name=SPLIT_REF_EXEC,
                    broker_share=BROKER_SHARE_EXEC,
                    office_share=OFFICE_SHARE_EXEC,
                    executive_share=EXECUTIVE_SHARE_EXEC,
                    referral_share=REFERRAL_SHARE_EXEC,
                    valid_from=date(2026, 8, 11),
                )
            )
    else:
        exec_split.broker_share = BROKER_SHARE_EXEC
        exec_split.office_share = OFFICE_SHARE_EXEC
        exec_split.executive_share = EXECUTIVE_SHARE_EXEC
        exec_split.referral_share = REFERRAL_SHARE_EXEC
        exec_split.valid_from = date(2026, 8, 11)

    # Plan referidos V1 — vigente (valid_from más reciente).
    ref_from = date(2026, 8, 12)
    split = (
        session.query(CommissionSplitRule)
        .filter_by(organization_id=org.id, name=SPLIT_REF)
        .one_or_none()
    )
    if split is None:
        session.add(
            CommissionSplitRule(
                organization_id=org.id,
                name=SPLIT_REF,
                broker_share=BROKER_SHARE,
                office_share=OFFICE_SHARE,
                executive_share=EXECUTIVE_SHARE,
                referral_share=REFERRAL_SHARE,
                valid_from=ref_from,
            )
        )
        split_created = 1
    else:
        split.broker_share = BROKER_SHARE
        split.office_share = OFFICE_SHARE
        split.executive_share = EXECUTIVE_SHARE
        split.referral_share = REFERRAL_SHARE
        split.valid_from = ref_from
        split_created = 0

    session.flush()
    # ADR-011 F1 — default CRM catalogs (idempotent)
    from corredores.services.crm_catalog_seed import ensure_default_crm_catalogs

    crm_catalog = ensure_default_crm_catalogs(session, org.id)

    return {
        "organization_id": org.id,
        "lines_created": lines_n,
        "carriers_created": carriers_n,
        "commission_rules_created": rules_n,
        "split_rules_created": split_created,
        "plan_reference": PLAN_REF,
        "broker_plan_reference": SPLIT_REF,
        "executive_plan_reference": SPLIT_REF_EXEC,
        "referral_plan_reference": SPLIT_REF,
        "crm_catalog": crm_catalog,
    }
