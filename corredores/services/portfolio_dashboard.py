"""Dashboard de cartera — inventario + salud de cobro/renovación (no es Hoy ni Radar)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.enums import PaymentPromiseStatus, RenewalOpportunityStatus
from corredores.domain.models import (
    Carrier,
    Commission,
    CommissionSplit,
    InsuranceLine,
    Party,
    Payment,
    PaymentPlan,
    PaymentPromise,
    Policy,
    RenewalOpportunity,
)
from corredores.services.installment_status import (
    DerivedInstallmentStatus,
    derive_installment_status,
    outstanding_balance,
)
from corredores.services.radar import build_radar


@dataclass
class SliceRow:
    key: str
    label: str
    policies: int
    premium: Decimal
    open_balance: Decimal
    overdue_balance: Decimal


@dataclass
class AgingBucket:
    key: str
    label: str
    count: int
    amount: Decimal
    href: str


@dataclass
class OverdueRow:
    policy_id: str
    policy_number: str
    client_name: str
    carrier_name: str
    due_date: date
    days_overdue: int
    balance: Decimal
    installment_id: str


@dataclass
class PortfolioDashboard:
    as_of: date
    organization_name: str
    policies_active: int
    policies_total: int
    clients: int
    premium_annual: Decimal
    open_balance: Decimal
    open_installments: int
    overdue_balance: Decimal
    overdue_installments: int
    renewals_open: int
    renewals_premium: Decimal
    payments_mtd: Decimal
    payments_mtd_n: int
    commissions_cia: Decimal
    commissions_broker: Decimal
    commissions_executive: Decimal
    commissions_office: Decimal
    commissions_referral: Decimal
    promises_active: int
    promises_broken: int
    aging: list[AgingBucket] = field(default_factory=list)
    by_carrier: list[SliceRow] = field(default_factory=list)
    by_line: list[SliceRow] = field(default_factory=list)
    top_overdue: list[OverdueRow] = field(default_factory=list)
    radar_keys: dict = field(default_factory=dict)
    charts: dict = field(default_factory=dict)
    payments_trend: list[dict] = field(default_factory=list)


def _party_name(p: Party | None) -> str:
    if p is None:
        return "—"
    if getattr(p, "party_type", None) == "ORGANIZATION":
        return p.legal_name or p.trade_name or "—"
    name = " ".join(x for x in [p.first_name or "", p.last_name or ""] if x).strip()
    return name or "—"


def build_portfolio_dashboard(
    session: Session,
    organization_id: str,
    *,
    today: date | None = None,
    renewal_horizon_days: int = 90,
) -> PortfolioDashboard:
    today = today or date.today()
    month_start = today.replace(day=1)
    horizon = today + timedelta(days=renewal_horizon_days)

    org_name = "ESecureBroker"
    from corredores.domain.models import Organization

    org = session.get(Organization, organization_id)
    if org:
        org_name = org.name

    policies = session.query(Policy).filter_by(organization_id=organization_id).all()
    active = [p for p in policies if p.status == "ACTIVE"]
    client_ids = {p.client_party_id for p in active}

    premium_annual = sum(
        (p.annual_premium or p.gross_premium or p.net_premium or Decimal("0")) for p in active
    )

    carrier_map: dict[str, SliceRow] = {}
    line_map: dict[str, SliceRow] = {}
    for p in active:
        car = session.get(Carrier, p.carrier_id)
        line = session.get(InsuranceLine, p.insurance_line_id)
        prem = p.annual_premium or p.gross_premium or p.net_premium or Decimal("0")
        ck = car.code if car else "?"
        cl = car.name if car else "Sin compañía"
        lk = line.code if line else "?"
        ll = line.name if line else "Sin ramo"
        if ck not in carrier_map:
            carrier_map[ck] = SliceRow(ck, cl, 0, Decimal("0"), Decimal("0"), Decimal("0"))
        if lk not in line_map:
            line_map[lk] = SliceRow(lk, ll, 0, Decimal("0"), Decimal("0"), Decimal("0"))
        carrier_map[ck].policies += 1
        carrier_map[ck].premium += prem
        line_map[lk].policies += 1
        line_map[lk].premium += prem

    aging_defs = [
        ("1-30", "1–30 días", 1, 30),
        ("31-60", "31–60 días", 31, 60),
        ("61-90", "61–90 días", 61, 90),
        ("90+", "Más de 90", 91, 10_000),
    ]
    aging_counts = {k: 0 for k, *_ in aging_defs}
    aging_amts = {k: Decimal("0") for k, *_ in aging_defs}

    open_balance = Decimal("0")
    open_n = 0
    overdue_balance = Decimal("0")
    overdue_n = 0
    top_overdue: list[OverdueRow] = []

    plans = (
        session.query(PaymentPlan)
        .join(Policy, Policy.id == PaymentPlan.policy_id)
        .filter(Policy.organization_id == organization_id)
        .all()
    )
    for plan in plans:
        policy = session.get(Policy, plan.policy_id)
        if policy is None:
            continue
        car = session.get(Carrier, policy.carrier_id)
        line = session.get(InsuranceLine, policy.insurance_line_id)
        client = session.get(Party, policy.client_party_id)
        ck = car.code if car else "?"
        lk = line.code if line else "?"
        for inst in plan.installments:
            session.refresh(inst)
            bal = outstanding_balance(inst)
            if bal <= 0:
                continue
            st = derive_installment_status(inst, today)
            open_balance += bal
            open_n += 1
            if ck in carrier_map:
                carrier_map[ck].open_balance += bal
            if lk in line_map:
                line_map[lk].open_balance += bal
            if st == DerivedInstallmentStatus.OVERDUE or (
                inst.due_date and inst.due_date < today and bal > 0
            ):
                overdue_balance += bal
                overdue_n += 1
                days = (today - inst.due_date).days if inst.due_date else 0
                for key, _label, lo, hi in aging_defs:
                    if lo <= days <= hi:
                        aging_counts[key] += 1
                        aging_amts[key] += bal
                        break
                if ck in carrier_map:
                    carrier_map[ck].overdue_balance += bal
                if lk in line_map:
                    line_map[lk].overdue_balance += bal
                top_overdue.append(
                    OverdueRow(
                        policy_id=policy.id,
                        policy_number=policy.policy_number or policy.id[:8],
                        client_name=_party_name(client),
                        carrier_name=car.name if car else "—",
                        due_date=inst.due_date or today,
                        days_overdue=days,
                        balance=bal,
                        installment_id=inst.id,
                    )
                )

    top_overdue.sort(key=lambda r: (r.days_overdue, r.balance), reverse=True)

    renewals = (
        session.query(RenewalOpportunity)
        .filter_by(organization_id=organization_id)
        .filter(
            RenewalOpportunity.status.in_(
                [
                    RenewalOpportunityStatus.UPCOMING,
                    RenewalOpportunityStatus.CONTACT_PENDING,
                    RenewalOpportunityStatus.CONTACTED,
                    RenewalOpportunityStatus.QUOTING,
                    RenewalOpportunityStatus.PROPOSAL_SENT,
                    RenewalOpportunityStatus.WAITING_CLIENT,
                ]
            )
        )
        .all()
    )
    renewals_in_horizon = []
    renewals_premium = Decimal("0")
    for ren in renewals:
        if ren.target_date and ren.target_date > horizon:
            continue
        renewals_in_horizon.append(ren)
        pol = session.get(Policy, ren.previous_policy_id)
        renewals_premium += (
            (pol.annual_premium or pol.net_premium or Decimal("0")) if pol else Decimal("0")
        )

    pays = (
        session.query(Payment)
        .filter(
            Payment.organization_id == organization_id,
            Payment.payment_date >= month_start,
            Payment.payment_date <= today,
        )
        .all()
    )
    payments_mtd = sum((p.amount for p in pays), Decimal("0"))

    comms = session.query(Commission).filter_by(organization_id=organization_id).all()
    commissions_cia = sum((c.calculated_amount for c in comms), Decimal("0"))
    broker_t = office_t = exec_t = ref_t = Decimal("0")
    for c in comms:
        sp = session.query(CommissionSplit).filter_by(commission_id=c.id).first()
        if sp:
            broker_t += sp.broker_amount or Decimal("0")
            office_t += sp.office_amount or Decimal("0")
            exec_t += sp.executive_amount or Decimal("0")
            ref_t += sp.referral_amount or Decimal("0")

    promises_active = (
        session.query(PaymentPromise)
        .filter_by(organization_id=organization_id, status=PaymentPromiseStatus.ACTIVE)
        .count()
    )
    promises_broken = (
        session.query(PaymentPromise)
        .filter_by(organization_id=organization_id, status=PaymentPromiseStatus.BROKEN)
        .count()
    )

    aging = [
        AgingBucket(
            key=k,
            label=label,
            count=aging_counts[k],
            amount=aging_amts[k],
            href=f"/morosidad?aging={k}",
        )
        for k, label, _lo, _hi in aging_defs
    ]

    radar = build_radar(session, organization_id, today=today)

    # Tendencia de recaudación (últimos 6 meses, del más viejo al más nuevo).
    payments_trend: list[dict] = []
    cursor = today.replace(day=1)
    months: list[date] = []
    for _ in range(6):
        months.append(cursor)
        if cursor.month == 1:
            cursor = date(cursor.year - 1, 12, 1)
        else:
            cursor = date(cursor.year, cursor.month - 1, 1)
    months.reverse()
    for start in months:
        if start.month == 12:
            end = date(start.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)
        if end > today:
            end = today
        month_pays = (
            session.query(Payment)
            .filter(
                Payment.organization_id == organization_id,
                Payment.payment_date >= start,
                Payment.payment_date <= end,
            )
            .all()
        )
        payments_trend.append(
            {
                "label": f"{start.year}-{start.month:02d}",
                "amount": float(sum((p.amount for p in month_pays), Decimal("0"))),
                "count": len(month_pays),
            }
        )

    current_open_not_overdue = open_balance - overdue_balance
    if current_open_not_overdue < 0:
        current_open_not_overdue = Decimal("0")

    charts = {
        "aging": {
            "labels": [a.label for a in aging],
            "amounts": [float(a.amount) for a in aging],
            "counts": [a.count for a in aging],
        },
        "carriers": {
            "labels": [r.label for r in sorted(carrier_map.values(), key=lambda x: x.premium, reverse=True)],
            "premiums": [
                float(r.premium)
                for r in sorted(carrier_map.values(), key=lambda x: x.premium, reverse=True)
            ],
            "overdue": [
                float(r.overdue_balance)
                for r in sorted(carrier_map.values(), key=lambda x: x.premium, reverse=True)
            ],
        },
        "lines": {
            "labels": [r.key for r in sorted(line_map.values(), key=lambda x: x.premium, reverse=True)],
            "premiums": [
                float(r.premium)
                for r in sorted(line_map.values(), key=lambda x: x.premium, reverse=True)
            ],
        },
        "money": {
            "labels": ["Vencido", "Por vencer", "Recaudado mes"],
            "amounts": [
                float(overdue_balance),
                float(current_open_not_overdue),
                float(payments_mtd),
            ],
        },
        "commissions": {
            "labels": ["Agente", "Ejecutivo", "Oficina", "Referido"],
            "amounts": [
                float(broker_t),
                float(exec_t),
                float(office_t),
                float(ref_t),
            ],
        },
        "trend": {
            "labels": [p["label"] for p in payments_trend],
            "amounts": [p["amount"] for p in payments_trend],
        },
    }

    return PortfolioDashboard(
        as_of=today,
        organization_name=org_name,
        policies_active=len(active),
        policies_total=len(policies),
        clients=len(client_ids),
        premium_annual=premium_annual,
        open_balance=open_balance,
        open_installments=open_n,
        overdue_balance=overdue_balance,
        overdue_installments=overdue_n,
        renewals_open=len(renewals_in_horizon),
        renewals_premium=renewals_premium,
        payments_mtd=payments_mtd,
        payments_mtd_n=len(pays),
        commissions_cia=commissions_cia,
        commissions_broker=broker_t,
        commissions_executive=exec_t,
        commissions_office=office_t,
        commissions_referral=ref_t,
        promises_active=promises_active,
        promises_broken=promises_broken,
        aging=aging,
        by_carrier=sorted(carrier_map.values(), key=lambda r: r.premium, reverse=True),
        by_line=sorted(line_map.values(), key=lambda r: r.premium, reverse=True),
        top_overdue=top_overdue[:20],
        radar_keys={
            "por_cobrar": radar.por_cobrar.amount,
            "por_renovar": radar.por_renovar.amount,
            "en_riesgo": radar.en_riesgo.amount,
        },
        charts=charts,
        payments_trend=payments_trend,
    )
