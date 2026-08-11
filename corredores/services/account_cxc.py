"""Estados de cuenta (CxC) y análisis de morosidad.

Domain Truth only: OVERDUE = due_date < today AND balance > 0.
Never invents mora from Excel colors.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.models import (
    Party,
    Payment,
    PaymentPlan,
    Policy,
)
from corredores.services.installment_status import (
    allocated_total,
    derive_installment_status,
    outstanding_balance,
)


AGING_DEFS: list[tuple[str, str, int, int]] = [
    ("1-30", "1–30 días", 1, 30),
    ("31-60", "31–60 días", 31, 60),
    ("61-90", "61–90 días", 61, 90),
    ("90+", "Más de 90", 91, 10_000),
]


def aging_key_for_days(days: int) -> str | None:
    if days < 1:
        return None
    for key, _label, lo, hi in AGING_DEFS:
        if lo <= days <= hi:
            return key
    return "90+"


def aging_label(key: str) -> str:
    for k, label, *_ in AGING_DEFS:
        if k == key:
            return label
    return key


def _party_name(p: Party | None) -> str:
    if p is None:
        return "—"
    if getattr(p, "party_type", None) == "ORGANIZATION":
        return p.legal_name or p.trade_name or p.id
    return " ".join(x for x in [p.first_name or "", p.last_name or ""] if x).strip() or p.id


@dataclass
class StatementLine:
    kind: str  # CUOTA | PAGO
    date: date
    policy_id: str
    policy_number: str | None
    installment_id: str | None
    installment_number: int | None
    description: str
    debit: Decimal  # cargo (cuota)
    credit: Decimal  # abono (pago)
    balance_after: Decimal | None = None
    status: str | None = None
    days_overdue: int = 0


@dataclass
class AccountStatement:
    as_of: date
    party_id: str
    party_name: str
    national_id: str | None
    open_balance: Decimal
    overdue_balance: Decimal
    overdue_count: int
    installments: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    ledger: list[StatementLine] = field(default_factory=list)
    aging: list[dict] = field(default_factory=list)


@dataclass
class MorosityAnalysis:
    as_of: date
    overdue_balance: Decimal
    overdue_count: int
    open_balance: Decimal
    clients_overdue: int
    aging: list[dict] = field(default_factory=list)
    top_debtors: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)


def build_account_statement(
    session: Session,
    organization_id: str,
    party_id: str,
    *,
    today: date | None = None,
) -> AccountStatement:
    today = today or date.today()
    party = session.get(Party, party_id)
    if party is None or party.organization_id != organization_id:
        raise ValueError("cliente no encontrado")

    policies = (
        session.query(Policy)
        .filter_by(organization_id=organization_id, client_party_id=party_id)
        .all()
    )
    policy_ids = [p.id for p in policies]
    policy_map = {p.id: p for p in policies}

    installments: list[dict] = []
    open_balance = Decimal("0")
    overdue_balance = Decimal("0")
    overdue_count = 0
    aging_amts = {k: Decimal("0") for k, *_ in AGING_DEFS}
    aging_counts = {k: 0 for k, *_ in AGING_DEFS}
    ledger_events: list[StatementLine] = []

    for p in policies:
        plan = session.query(PaymentPlan).filter_by(policy_id=p.id).first()
        if plan is None:
            continue
        for inst in sorted(plan.installments, key=lambda i: (i.due_date, i.installment_number)):
            session.refresh(inst)
            bal = outstanding_balance(inst)
            paid = allocated_total(inst)
            status = derive_installment_status(inst, today).value
            days = (today - inst.due_date).days if inst.due_date and bal > 0 and inst.due_date < today else 0
            installments.append(
                {
                    "installment_id": inst.id,
                    "policy_id": p.id,
                    "policy_number": p.policy_number,
                    "number": inst.installment_number,
                    "due_date": inst.due_date,
                    "amount": inst.amount,
                    "paid": paid,
                    "balance": bal,
                    "status": status,
                    "days_overdue": days,
                    "aging": aging_key_for_days(days) if days else None,
                }
            )
            ledger_events.append(
                StatementLine(
                    kind="CUOTA",
                    date=inst.due_date,
                    policy_id=p.id,
                    policy_number=p.policy_number,
                    installment_id=inst.id,
                    installment_number=inst.installment_number,
                    description=f"Cuota {inst.installment_number}",
                    debit=inst.amount,
                    credit=Decimal("0"),
                    status=status,
                    days_overdue=days,
                )
            )
            if bal > 0:
                open_balance += bal
            if days > 0:
                overdue_balance += bal
                overdue_count += 1
                key = aging_key_for_days(days)
                if key:
                    aging_amts[key] += bal
                    aging_counts[key] += 1

    payments_out: list[dict] = []
    if policy_ids:
        pays = (
            session.query(Payment)
            .filter(
                Payment.organization_id == organization_id,
                Payment.policy_id.in_(policy_ids),
            )
            .order_by(Payment.payment_date.desc(), Payment.created_at.desc())
            .all()
        )
        for pay in pays:
            pol = policy_map.get(pay.policy_id)
            payments_out.append(
                {
                    "id": pay.id,
                    "policy_id": pay.policy_id,
                    "policy_number": pol.policy_number if pol else None,
                    "date": pay.payment_date,
                    "amount": pay.amount,
                    "method": pay.method,
                    "reference": pay.reference,
                }
            )
            ledger_events.append(
                StatementLine(
                    kind="PAGO",
                    date=pay.payment_date,
                    policy_id=pay.policy_id,
                    policy_number=pol.policy_number if pol else None,
                    installment_id=None,
                    installment_number=None,
                    description=f"Pago {pay.method or ''}".strip()
                    + (f" · {pay.reference}" if pay.reference else ""),
                    debit=Decimal("0"),
                    credit=pay.amount,
                )
            )

    ledger_events.sort(key=lambda x: (x.date, 0 if x.kind == "CUOTA" else 1))
    running = Decimal("0")
    for line in ledger_events:
        running += line.debit - line.credit
        line.balance_after = running

    aging = [
        {
            "key": k,
            "label": label,
            "count": aging_counts[k],
            "amount": aging_amts[k],
        }
        for k, label, _lo, _hi in AGING_DEFS
    ]

    return AccountStatement(
        as_of=today,
        party_id=party.id,
        party_name=_party_name(party),
        national_id=party.national_id,
        open_balance=open_balance,
        overdue_balance=overdue_balance,
        overdue_count=overdue_count,
        installments=installments,
        payments=payments_out,
        ledger=ledger_events,
        aging=aging,
    )


def build_morosity_analysis(
    session: Session,
    organization_id: str,
    *,
    today: date | None = None,
    aging: str | None = None,
) -> MorosityAnalysis:
    today = today or date.today()
    aging_n = (aging or "").strip().lower()
    if aging_n in {"1–30", "1-30 dias", "1-30 días"}:
        aging_n = "1-30"
    elif aging_n in {"31–60", "31-60 dias"}:
        aging_n = "31-60"
    elif aging_n in {"61–90", "61-90 dias"}:
        aging_n = "61-90"
    elif aging_n in {"más de 90", "mas de 90", "90"}:
        aging_n = "90+"

    aging_amts = {k: Decimal("0") for k, *_ in AGING_DEFS}
    aging_counts = {k: 0 for k, *_ in AGING_DEFS}
    rows: list[dict] = []
    debtor_map: dict[str, dict] = {}
    open_balance = Decimal("0")
    overdue_balance = Decimal("0")
    overdue_count = 0

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
        party = session.get(Party, policy.client_party_id)
        for inst in plan.installments:
            session.refresh(inst)
            bal = outstanding_balance(inst)
            if bal <= 0:
                continue
            open_balance += bal
            days = (today - inst.due_date).days if inst.due_date and inst.due_date < today else 0
            if days < 1:
                continue
            key = aging_key_for_days(days) or "90+"
            if aging_n and key != aging_n:
                continue
            overdue_balance += bal
            overdue_count += 1
            aging_amts[key] += bal
            aging_counts[key] += 1
            status = derive_installment_status(inst, today).value
            row = {
                "party_id": policy.client_party_id,
                "party_name": _party_name(party),
                "policy_id": policy.id,
                "policy_number": policy.policy_number,
                "installment_id": inst.id,
                "installment_number": inst.installment_number,
                "due_date": inst.due_date,
                "amount": inst.amount,
                "balance": bal,
                "status": status,
                "days_overdue": days,
                "aging": key,
                "aging_label": aging_label(key),
            }
            rows.append(row)
            d = debtor_map.setdefault(
                policy.client_party_id,
                {
                    "party_id": policy.client_party_id,
                    "party_name": _party_name(party),
                    "balance": Decimal("0"),
                    "count": 0,
                    "max_days": 0,
                },
            )
            d["balance"] += bal
            d["count"] += 1
            d["max_days"] = max(d["max_days"], days)

    rows.sort(key=lambda r: (-r["days_overdue"], -r["balance"], r["party_name"]))
    top_debtors = sorted(debtor_map.values(), key=lambda d: d["balance"], reverse=True)[:15]

    return MorosityAnalysis(
        as_of=today,
        overdue_balance=overdue_balance,
        overdue_count=overdue_count,
        open_balance=open_balance,
        clients_overdue=len(debtor_map),
        aging=[
            {
                "key": k,
                "label": label,
                "count": aging_counts[k],
                "amount": aging_amts[k],
            }
            for k, label, _lo, _hi in AGING_DEFS
        ],
        top_debtors=top_debtors,
        rows=rows,
    )


def csv_estado_cuenta(
    session: Session, organization_id: str, party_id: str, *, today: date | None = None
) -> str:
    stmt = build_account_statement(session, organization_id, party_id, today=today)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "tipo",
            "fecha",
            "poliza",
            "cuota",
            "descripcion",
            "cargo",
            "abono",
            "saldo_corrido",
            "estado",
            "dias_mora",
        ]
    )
    for line in stmt.ledger:
        w.writerow(
            [
                line.kind,
                line.date.isoformat() if line.date else "",
                line.policy_number or "",
                line.installment_number or "",
                line.description,
                str(line.debit),
                str(line.credit),
                str(line.balance_after if line.balance_after is not None else ""),
                line.status or "",
                line.days_overdue or "",
            ]
        )
    return buf.getvalue()


def csv_morosidad(
    session: Session, organization_id: str, *, today: date | None = None, aging: str | None = None
) -> str:
    analysis = build_morosity_analysis(session, organization_id, today=today, aging=aging)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "cliente",
            "poliza",
            "cuota",
            "vence",
            "monto",
            "saldo",
            "estado",
            "dias_mora",
            "banda_aging",
        ]
    )
    for r in analysis.rows:
        w.writerow(
            [
                r["party_name"],
                r["policy_number"] or "",
                r["installment_number"],
                r["due_date"].isoformat() if r["due_date"] else "",
                str(r["amount"]),
                str(r["balance"]),
                r["status"],
                r["days_overdue"],
                r["aging_label"],
            ]
        )
    return buf.getvalue()
