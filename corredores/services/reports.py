"""Operational reports — cartera, cobranza, renovaciones, pagos (CSV + resumen)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.models import (
    Carrier,
    Commission,
    InsuranceLine,
    Party,
    Payment,
    PaymentPlan,
    Policy,
    PolicyTerm,
    RenewalOpportunity,
)
from corredores.services.cobranza_board import build_cobranza_board
from corredores.services.installment_status import derive_installment_status, outstanding_balance


@dataclass
class ReportSummary:
    policies_active: int
    installments_open: int
    balance_open: Decimal
    renewals_open: int
    payments_mtd: int
    payments_mtd_amount: Decimal
    commissions_count: int
    commissions_amount: Decimal


def _party_name(p: Party | None) -> str:
    if p is None:
        return ""
    if getattr(p, "party_type", None) == "ORGANIZATION":
        return p.legal_name or p.trade_name or ""
    return " ".join(x for x in [p.first_name or "", p.last_name or ""] if x).strip()


def build_report_summary(
    session: Session, organization_id: str, *, today: date | None = None
) -> ReportSummary:
    today = today or date.today()
    month_start = today.replace(day=1)
    policies = (
        session.query(Policy)
        .filter_by(organization_id=organization_id, status="ACTIVE")
        .all()
    )
    board = build_cobranza_board(session, organization_id, today=today)
    balance = sum((board.totals.get(k, Decimal("0")) for k in board.totals), Decimal("0"))
    open_n = sum(len(v) for v in board.bands.values())
    renewals = (
        session.query(RenewalOpportunity)
        .filter_by(organization_id=organization_id)
        .filter(RenewalOpportunity.status.in_(["UPCOMING", "CONTACT_PENDING", "CONTACTED", "QUOTING", "PROPOSAL_SENT", "WAITING_CLIENT"]))
        .count()
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
    comms = session.query(Commission).filter_by(organization_id=organization_id).all()
    return ReportSummary(
        policies_active=len(policies),
        installments_open=open_n,
        balance_open=balance,
        renewals_open=renewals,
        payments_mtd=len(pays),
        payments_mtd_amount=sum((p.amount for p in pays), Decimal("0")),
        commissions_count=len(comms),
        commissions_amount=sum((c.calculated_amount for c in comms), Decimal("0")),
    )


def csv_cartera(session: Session, organization_id: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "policy_number",
            "status",
            "client",
            "national_id",
            "carrier",
            "line",
            "effective_date",
            "expiration_date",
            "annual_premium",
            "net_premium",
        ]
    )
    rows = (
        session.query(Policy)
        .filter_by(organization_id=organization_id)
        .order_by(Policy.created_at.desc())
        .all()
    )
    for p in rows:
        party = session.get(Party, p.client_party_id)
        carrier = session.get(Carrier, p.carrier_id)
        line = session.get(InsuranceLine, p.insurance_line_id)
        term = session.query(PolicyTerm).filter_by(policy_id=p.id).first()
        w.writerow(
            [
                p.policy_number or "",
                p.status,
                _party_name(party),
                (party.national_id if party else "") or "",
                carrier.name if carrier else "",
                line.code if line else "",
                term.effective_date.isoformat() if term else "",
                term.expiration_date.isoformat() if term else "",
                str(p.annual_premium or ""),
                str(p.net_premium or ""),
            ]
        )
    return buf.getvalue()


def csv_cobranza(session: Session, organization_id: str, *, today: date | None = None) -> str:
    board = build_cobranza_board(session, organization_id, today=today)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "band",
            "client",
            "policy_number",
            "installment_number",
            "due_date",
            "amount",
            "balance",
            "status",
        ]
    )
    for band, rows in board.bands.items():
        for r in rows:
            w.writerow(
                [
                    band,
                    r.party_name,
                    r.policy_number or "",
                    r.installment_number,
                    r.due_date.isoformat(),
                    str(r.amount),
                    str(r.balance),
                    r.status,
                ]
            )
    return buf.getvalue()


def csv_renovaciones(session: Session, organization_id: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["status", "target_date", "policy_number", "client", "carrier", "line"])
    rows = (
        session.query(RenewalOpportunity)
        .filter_by(organization_id=organization_id)
        .order_by(RenewalOpportunity.target_date)
        .all()
    )
    for ren in rows:
        pol = session.get(Policy, ren.previous_policy_id)
        party = session.get(Party, pol.client_party_id) if pol else None
        carrier = session.get(Carrier, pol.carrier_id) if pol else None
        line = session.get(InsuranceLine, pol.insurance_line_id) if pol else None
        w.writerow(
            [
                ren.status,
                ren.target_date.isoformat() if ren.target_date else "",
                pol.policy_number if pol else "",
                _party_name(party),
                carrier.name if carrier else "",
                line.code if line else "",
            ]
        )
    return buf.getvalue()


def csv_pagos(session: Session, organization_id: str, *, today: date | None = None) -> str:
    today = today or date.today()
    month_start = today.replace(day=1)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["payment_date", "amount", "method", "reference", "policy_number", "client"])
    pays = (
        session.query(Payment)
        .filter(
            Payment.organization_id == organization_id,
            Payment.payment_date >= month_start,
            Payment.payment_date <= today,
        )
        .order_by(Payment.payment_date.desc())
        .all()
    )
    for pay in pays:
        pol = session.get(Policy, pay.policy_id)
        party = session.get(Party, pol.client_party_id) if pol else None
        w.writerow(
            [
                pay.payment_date.isoformat(),
                str(pay.amount),
                pay.method or "",
                pay.reference or "",
                pol.policy_number if pol else "",
                _party_name(party),
            ]
        )
    return buf.getvalue()


def csv_comisiones(session: Session, organization_id: str) -> str:
    from corredores.domain.models import CommissionSplit

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "policy_number",
            "client",
            "base_amount",
            "rate",
            "cia_amount",
            "broker",
            "executive",
            "office",
            "referral",
            "calculated_at",
        ]
    )
    rows = (
        session.query(Commission)
        .filter_by(organization_id=organization_id)
        .order_by(Commission.calculated_at.desc())
        .all()
    )
    for c in rows:
        pol = session.get(Policy, c.policy_id)
        party = session.get(Party, pol.client_party_id) if pol else None
        sp = session.query(CommissionSplit).filter_by(commission_id=c.id).first()
        w.writerow(
            [
                pol.policy_number if pol else "",
                _party_name(party),
                str(c.base_amount),
                str(c.rate),
                str(c.calculated_amount),
                str(sp.broker_amount if sp else ""),
                str(sp.executive_amount if sp else ""),
                str(sp.office_amount if sp else ""),
                str(sp.referral_amount if sp else ""),
                c.calculated_at.isoformat() if c.calculated_at else "",
            ]
        )
    return buf.getvalue()


def csv_cotizaciones(session: Session, organization_id: str) -> str:
    from corredores.domain.models import QuoteRequest
    from corredores.services.quote_orchestrator import build_comparator

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "quote_request_id",
            "line",
            "created_at",
            "carrier",
            "source",
            "status",
            "premium",
            "currency",
        ]
    )
    qrs = (
        session.query(QuoteRequest)
        .filter_by(organization_id=organization_id)
        .order_by(QuoteRequest.created_at.desc())
        .all()
    )
    for qr in qrs:
        line = session.get(InsuranceLine, qr.insurance_line_id)
        try:
            rows = build_comparator(session, qr.id)
        except Exception:
            rows = []
        if not rows:
            w.writerow(
                [
                    qr.id,
                    line.code if line else "",
                    qr.created_at.isoformat() if qr.created_at else "",
                    "",
                    "",
                    "EMPTY",
                    "",
                    "",
                ]
            )
            continue
        for r in rows:
            w.writerow(
                [
                    qr.id,
                    line.code if line else "",
                    qr.created_at.isoformat() if qr.created_at else "",
                    r.carrier_name,
                    r.source,
                    r.status,
                    str(r.premium) if r.premium is not None else "",
                    r.currency,
                ]
            )
    return buf.getvalue()


def report_preview_rows(
    session: Session, organization_id: str, *, today: date | None = None
) -> dict:
    """In-page preview tables for reportes UI."""
    today = today or date.today()
    month_start = today.replace(day=1)
    policies = []
    for p in (
        session.query(Policy)
        .filter_by(organization_id=organization_id)
        .order_by(Policy.created_at.desc())
        .limit(12)
        .all()
    ):
        party = session.get(Party, p.client_party_id)
        carrier = session.get(Carrier, p.carrier_id)
        line = session.get(InsuranceLine, p.insurance_line_id)
        policies.append(
            {
                "id": p.id,
                "number": p.policy_number or p.id[:8],
                "client": _party_name(party) or "—",
                "carrier": carrier.name if carrier else "—",
                "line": line.code if line else "—",
                "status": p.status,
                "premium": p.annual_premium or p.net_premium,
            }
        )
    board = build_cobranza_board(session, organization_id, today=today)
    cobranza = []
    for band, rows in board.bands.items():
        for r in rows[:8]:
            cobranza.append(
                {
                    "band": band,
                    "client": r.party_name,
                    "policy": r.policy_number or "—",
                    "due": r.due_date,
                    "balance": r.balance,
                    "status": r.status,
                }
            )
            if len(cobranza) >= 12:
                break
        if len(cobranza) >= 12:
            break
    renewals = []
    for ren in (
        session.query(RenewalOpportunity)
        .filter_by(organization_id=organization_id)
        .order_by(RenewalOpportunity.target_date)
        .limit(12)
        .all()
    ):
        pol = session.get(Policy, ren.previous_policy_id)
        party = session.get(Party, pol.client_party_id) if pol else None
        renewals.append(
            {
                "id": ren.id,
                "status": ren.status,
                "target": ren.target_date,
                "policy": pol.policy_number if pol else "—",
                "client": _party_name(party) or "—",
            }
        )
    payments = []
    for pay in (
        session.query(Payment)
        .filter(
            Payment.organization_id == organization_id,
            Payment.payment_date >= month_start,
            Payment.payment_date <= today,
        )
        .order_by(Payment.payment_date.desc())
        .limit(12)
        .all()
    ):
        pol = session.get(Policy, pay.policy_id)
        payments.append(
            {
                "date": pay.payment_date,
                "amount": pay.amount,
                "method": pay.method or "—",
                "policy": pol.policy_number if pol else "—",
            }
        )
    return {
        "policies": policies,
        "cobranza": cobranza,
        "renewals": renewals,
        "payments": payments,
    }

def policy_installment_rows(
    session: Session, policy_id: str, *, today: date | None = None
) -> list[dict]:
    today = today or date.today()
    plan = session.query(PaymentPlan).filter_by(policy_id=policy_id).first()
    if plan is None:
        return []
    out = []
    for inst in sorted(plan.installments, key=lambda i: i.installment_number):
        out.append(
            {
                "id": inst.id,
                "number": inst.installment_number,
                "due_date": inst.due_date,
                "amount": inst.amount,
                "balance": outstanding_balance(inst),
                "status": derive_installment_status(inst, today).value,
            }
        )
    return out
