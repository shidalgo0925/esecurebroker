"""Commission plan catalog — rates by line + internal split (PLAN_COMISIONES_V1)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.models import (
    Carrier,
    Commission,
    CommissionRule,
    CommissionSplit,
    CommissionSplitRule,
    InsuranceLine,
    Organization,
    Policy,
)


PLAN_REF = "PLAN_COMISIONES_V1"
# Sin ejecutivo ni referido (variante).
SPLIT_REF_SOLO = "PLAN_CORREDORES_V1 — 70/30 Agente-Oficina"
# Con ejecutivo, sin referido (variante).
SPLIT_REF_EXEC = "PLAN_EJECUTIVOS_V1 — 60/10/30 Agente-Ejecutivo-Oficina"
EXEC_PLAN_REF = "PLAN_EJECUTIVOS_V1"
# Vigente por defecto: casa paga referido + ejecutivo.
SPLIT_REF = "PLAN_REFERIDOS_V1 — 55/10/30/5 Agente-Ejecutivo-Oficina-Referido"
REF_PLAN_REF = "PLAN_REFERIDOS_V1"

# PLAN_REFERIDOS_V1 — distribución interna de la comisión Cia (vigente).
BROKER_SHARE = Decimal("0.55")
EXECUTIVE_SHARE = Decimal("0.10")
OFFICE_SHARE = Decimal("0.30")
REFERRAL_SHARE = Decimal("0.05")

# PLAN_EJECUTIVOS_V1 — con ejecutivo, sin referido.
BROKER_SHARE_EXEC = Decimal("0.60")
EXECUTIVE_SHARE_EXEC = Decimal("0.10")
OFFICE_SHARE_EXEC = Decimal("0.30")
REFERRAL_SHARE_EXEC = Decimal("0")

# PLAN_CORREDORES_V1 — sin ejecutivo ni referido.
BROKER_SHARE_SOLO = Decimal("0.70")
OFFICE_SHARE_SOLO = Decimal("0.30")
EXECUTIVE_SHARE_SOLO = Decimal("0")
REFERRAL_SHARE_SOLO = Decimal("0")

# Ramo → tasa comisión compañía (sobre prima anual).
LINE_RATES: dict[str, Decimal] = {
    "AUTO": Decimal("0.20"),
    "MOTO": Decimal("0.20"),
    "AP": Decimal("0.20"),
    "HOGAR": Decimal("0.20"),
    "INCENDIO": Decimal("0.25"),
    "VIAJE": Decimal("0.25"),
    "TRANSPORTE": Decimal("0.15"),
    "SALUD": Decimal("0.10"),
    "VIDA": Decimal("0.35"),
}

LINE_LABELS: dict[str, str] = {
    "AUTO": "Automóvil",
    "MOTO": "Moto",
    "AP": "Asiento / Accidentes personales",
    "HOGAR": "Multirriesgo residencial",
    "INCENDIO": "Incendio y aliadas",
    "VIAJE": "Seguro de viaje",
    "TRANSPORTE": "Transporte de carga",
    "SALUD": "Salud individual",
    "VIDA": "Vida individual",
}


@dataclass
class CommissionPlanView:
    organization_name: str
    agreement_reference: str
    calculation_base: str
    split_name: str
    split_reference: str
    broker_share: Decimal
    office_share: Decimal
    executive_share: Decimal
    referral_share: Decimal
    line_rates: list[dict]
    carriers: list[dict]
    applied_count: int
    applied_total: Decimal
    broker_total: Decimal
    office_total: Decimal
    executive_total: Decimal
    referral_total: Decimal
    roles: list[dict]
    example: dict
    executive_plan: dict
    referral_plan: dict


def resolve_active_split_rule(session: Session, organization_id: str) -> CommissionSplitRule | None:
    """Prefer PLAN_REFERIDOS_V1; else newest valid_from."""
    preferred = (
        session.query(CommissionSplitRule)
        .filter_by(organization_id=organization_id, name=SPLIT_REF)
        .one_or_none()
    )
    if preferred is not None:
        return preferred
    return (
        session.query(CommissionSplitRule)
        .filter_by(organization_id=organization_id)
        .order_by(CommissionSplitRule.valid_from.desc())
        .first()
    )


def build_commission_plan_view(session: Session, organization_id: str) -> CommissionPlanView:
    org = session.get(Organization, organization_id)
    rules = (
        session.query(CommissionRule)
        .filter_by(organization_id=organization_id)
        .order_by(CommissionRule.valid_from.desc())
        .all()
    )
    by_line: dict[str, CommissionRule] = {}
    for rule in rules:
        line = session.get(InsuranceLine, rule.insurance_line_id)
        if line is None:
            continue
        if line.code in by_line and rule.agreement_reference != PLAN_REF:
            continue
        if line.code not in by_line or rule.agreement_reference == PLAN_REF:
            by_line[line.code] = rule

    line_rates = []
    for code, rate in LINE_RATES.items():
        rule = by_line.get(code)
        line_rates.append(
            {
                "code": code,
                "label": LINE_LABELS.get(code, code),
                "rate": rule.rate if rule else rate,
                "rate_pct": f"{((rule.rate if rule else rate) * 100):.0f}%",
                "base": rule.calculation_base if rule else "ANNUAL_PREMIUM",
                "carrier_specific": bool(rule and rule.carrier_id),
                "agreement": rule.agreement_reference if rule else PLAN_REF,
            }
        )

    split = resolve_active_split_rule(session, organization_id)
    broker_share = split.broker_share if split else BROKER_SHARE
    office_share = split.office_share if split else OFFICE_SHARE
    executive_share = split.executive_share if split else EXECUTIVE_SHARE
    referral_share = split.referral_share if split else REFERRAL_SHARE

    carriers = [
        {"code": c.code, "name": c.name, "active": c.active}
        for c in session.query(Carrier)
        .filter_by(organization_id=organization_id)
        .order_by(Carrier.name)
        .all()
    ]
    applied = session.query(Commission).filter_by(organization_id=organization_id).all()
    total = sum((c.calculated_amount for c in applied), Decimal("0"))
    broker_total = Decimal("0")
    office_total = Decimal("0")
    executive_total = Decimal("0")
    referral_total = Decimal("0")
    for c in applied:
        sp = session.query(CommissionSplit).filter_by(commission_id=c.id).first()
        if sp:
            broker_total += sp.broker_amount or Decimal("0")
            office_total += sp.office_amount or Decimal("0")
            executive_total += sp.executive_amount or Decimal("0")
            referral_total += sp.referral_amount or Decimal("0")

    example_premium = Decimal("1000.00")
    example_cia = (example_premium * Decimal("0.20")).quantize(Decimal("0.01"))
    example = {
        "premium": example_premium,
        "cia_rate": "20%",
        "cia": example_cia,
        "broker": (example_cia * broker_share).quantize(Decimal("0.01")),
        "office": (example_cia * office_share).quantize(Decimal("0.01")),
        "executive": (example_cia * executive_share).quantize(Decimal("0.01")),
        "referral": (example_cia * referral_share).quantize(Decimal("0.01")),
    }
    roles = [
        {
            "role": "Agente / corredor productor",
            "code": "broker_share",
            "share": broker_share,
            "share_pct": f"{(broker_share * 100):.0f}%",
            "meaning": "Quien origina o coloca la póliza",
        },
        {
            "role": "Ejecutivo de cuenta",
            "code": "executive_share",
            "share": executive_share,
            "share_pct": f"{(executive_share * 100):.0f}%",
            "meaning": "Supervisa cartera, gestiona renovación y cobranza de la cuenta",
        },
        {
            "role": "Oficina",
            "code": "office_share",
            "share": office_share,
            "share_pct": f"{(office_share * 100):.0f}%",
            "meaning": "Casa de corredores (soporte, marca, overhead)",
        },
        {
            "role": "Referido",
            "code": "referral_share",
            "share": referral_share,
            "share_pct": f"{(referral_share * 100):.0f}%",
            "meaning": "Quien trae el lead / referido comercial",
        },
    ]
    executive_plan = {
        "reference": EXEC_PLAN_REF,
        "split_name": SPLIT_REF_EXEC,
        "broker_pct": f"{(BROKER_SHARE_EXEC * 100):.0f}%",
        "executive_pct": f"{(EXECUTIVE_SHARE_EXEC * 100):.0f}%",
        "office_pct": f"{(OFFICE_SHARE_EXEC * 100):.0f}%",
        "referral_pct": f"{(REFERRAL_SHARE_EXEC * 100):.0f}%",
        "solo_reference": SPLIT_REF_SOLO,
        "solo_broker_pct": f"{(BROKER_SHARE_SOLO * 100):.0f}%",
        "solo_office_pct": f"{(OFFICE_SHARE_SOLO * 100):.0f}%",
        "rule": (
            "El ejecutivo de cuenta recibe 10% de la comisión Cia. "
            "Ese 10% se descuenta del share del agente (70% → 60%); "
            "la oficina se mantiene en 30%."
        ),
    }
    referral_plan = {
        "reference": REF_PLAN_REF,
        "split_name": SPLIT_REF,
        "broker_pct": f"{(BROKER_SHARE * 100):.0f}%",
        "executive_pct": f"{(EXECUTIVE_SHARE * 100):.0f}%",
        "office_pct": f"{(OFFICE_SHARE * 100):.0f}%",
        "referral_pct": f"{(REFERRAL_SHARE * 100):.0f}%",
        "exec_reference": SPLIT_REF_EXEC,
        "solo_reference": SPLIT_REF_SOLO,
        "rule": (
            "El referido recibe 5% de la comisión Cia. "
            "Ese 5% se descuenta del share del agente (60% → 55%); "
            "ejecutivo 10% y oficina 30% no cambian."
        ),
    }

    return CommissionPlanView(
        organization_name=org.name if org else "ESecureBroker",
        agreement_reference=PLAN_REF,
        calculation_base="ANNUAL_PREMIUM",
        split_name=split.name if split else SPLIT_REF,
        split_reference=SPLIT_REF,
        broker_share=broker_share,
        office_share=office_share,
        executive_share=executive_share,
        referral_share=referral_share,
        line_rates=line_rates,
        carriers=carriers,
        applied_count=len(applied),
        applied_total=total,
        broker_total=broker_total,
        office_total=office_total,
        executive_total=executive_total,
        referral_total=referral_total,
        roles=roles,
        example=example,
        executive_plan=executive_plan,
        referral_plan=referral_plan,
    )


def list_applied_commissions(session: Session, organization_id: str, limit: int = 50) -> list[dict]:
    rows = (
        session.query(Commission)
        .filter_by(organization_id=organization_id)
        .order_by(Commission.calculated_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for c in rows:
        pol = session.get(Policy, c.policy_id)
        split = session.query(CommissionSplit).filter_by(commission_id=c.id).first()
        out.append(
            {
                "id": c.id,
                "policy_number": pol.policy_number if pol else c.policy_id[:8],
                "policy_id": c.policy_id,
                "base_amount": c.base_amount,
                "rate": c.rate,
                "calculated_amount": c.calculated_amount,
                "broker_amount": split.broker_amount if split else None,
                "office_amount": split.office_amount if split else None,
                "executive_amount": split.executive_amount if split else None,
                "referral_amount": split.referral_amount if split else None,
                "calculated_at": c.calculated_at,
            }
        )
    return out
