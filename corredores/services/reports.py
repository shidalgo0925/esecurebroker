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


def cartera_print_rows(session: Session, organization_id: str) -> list[dict]:
    """Filas para reporte PDF/print de cartera (orden estable)."""
    rows: list[dict] = []
    policies = (
        session.query(Policy)
        .filter_by(organization_id=organization_id)
        .order_by(Policy.status.asc(), Policy.policy_number.asc())
        .all()
    )
    for p in policies:
        party = session.get(Party, p.client_party_id)
        carrier = session.get(Carrier, p.carrier_id)
        line = session.get(InsuranceLine, p.insurance_line_id)
        term = session.query(PolicyTerm).filter_by(policy_id=p.id).first()
        rows.append(
            {
                "number": p.policy_number or p.id[:8],
                "status": p.status,
                "client": _party_name(party) or "—",
                "carrier": carrier.name if carrier else "—",
                "line": line.code if line else "—",
                "effective": term.effective_date.isoformat() if term and term.effective_date else "—",
                "expiration": term.expiration_date.isoformat() if term and term.expiration_date else "—",
                "premium": p.annual_premium or p.net_premium or p.gross_premium,
            }
        )
    return rows


PRINT_REPORT_KEYS = (
    "cartera",
    "cobranza",
    "morosidad",
    "renovaciones",
    "pagos",
    "comisiones",
    "cotizaciones",
    "clientes",
    "reclamos",
    "oportunidades",
    "metas",
    "referidos",
)


def build_print_report(
    session: Session,
    organization_id: str,
    key: str,
    *,
    today: date | None = None,
) -> dict:
    """Especificación de reporte PDF/print (cabecera identidad + tabla + KPIs)."""
    today = today or date.today()
    key_n = (key or "").strip().lower()
    if key_n not in PRINT_REPORT_KEYS:
        raise ValueError(f"reporte desconocido: {key}")

    if key_n == "cartera":
        rows = cartera_print_rows(session, organization_id)
        premium_total = sum(
            (r["premium"] for r in rows if r.get("premium") is not None),
            Decimal("0"),
        )
        active_n = sum(1 for r in rows if r.get("status") == "ACTIVE")
        return {
            "key": key_n,
            "title": "Reporte de cartera",
            "subtitle": "Inventario de pólizas",
            "columns": [
                {"key": "number", "label": "Póliza", "mono": True},
                {"key": "status", "label": "Estado"},
                {"key": "client", "label": "Cliente"},
                {"key": "carrier", "label": "Cia"},
                {"key": "line", "label": "Ramo", "mono": True},
                {"key": "vigencia", "label": "Vigencia", "mono": True},
                {"key": "premium", "label": "Prima", "money": True},
            ],
            "rows": [
                {
                    **r,
                    "vigencia": f"{r['effective']} → {r['expiration']}",
                }
                for r in rows
            ],
            "kpis": [
                {"label": "Activas", "value": active_n},
                {"label": "Total pólizas", "value": len(rows)},
                {"label": "Prima (suma)", "value": premium_total, "money": True},
            ],
            "empty": "Sin pólizas en la cartera.",
        }

    if key_n == "cobranza":
        board = build_cobranza_board(session, organization_id, today=today)
        rows = []
        for band, band_rows in board.bands.items():
            for r in band_rows:
                rows.append(
                    {
                        "band": band,
                        "client": r.party_name or "—",
                        "policy": r.policy_number or "—",
                        "installment": r.installment_number,
                        "due": r.due_date.isoformat() if r.due_date else "—",
                        "amount": r.amount,
                        "balance": r.balance,
                        "status": r.status,
                    }
                )
        balance = sum((board.totals.get(k, Decimal("0")) for k in board.totals), Decimal("0"))
        return {
            "key": key_n,
            "title": "Reporte de cobranza",
            "subtitle": "Cuotas abiertas por banda operativa",
            "columns": [
                {"key": "band", "label": "Banda"},
                {"key": "client", "label": "Cliente"},
                {"key": "policy", "label": "Póliza", "mono": True},
                {"key": "installment", "label": "Cuota", "mono": True},
                {"key": "due", "label": "Vence", "mono": True},
                {"key": "amount", "label": "Monto", "money": True},
                {"key": "balance", "label": "Saldo", "money": True},
                {"key": "status", "label": "Estado"},
            ],
            "rows": rows,
            "kpis": [
                {"label": "Cuotas abiertas", "value": len(rows)},
                {"label": "Saldo abierto", "value": balance, "money": True},
            ],
            "empty": "Sin cuotas abiertas.",
        }

    if key_n == "morosidad":
        from corredores.services.account_cxc import build_morosity_analysis

        analysis = build_morosity_analysis(session, organization_id)
        rows = []
        for r in analysis.rows:
            rows.append(
                {
                    "client": r.get("party_name") or "—",
                    "policy": r.get("policy_number") or "—",
                    "due": r["due_date"].isoformat() if r.get("due_date") else "—",
                    "days": r.get("days_overdue") if r.get("days_overdue") is not None else "—",
                    "balance": r.get("balance"),
                    "band": r.get("aging_label") or r.get("aging") or "—",
                }
            )
        return {
            "key": key_n,
            "title": "Reporte de morosidad",
            "subtitle": "Cuotas vencidas con saldo (Domain Truth)",
            "columns": [
                {"key": "client", "label": "Cliente"},
                {"key": "policy", "label": "Póliza", "mono": True},
                {"key": "due", "label": "Venció", "mono": True},
                {"key": "days", "label": "Días", "mono": True},
                {"key": "band", "label": "Aging"},
                {"key": "balance", "label": "Saldo", "money": True},
            ],
            "rows": rows,
            "kpis": [
                {
                    "label": "Vencido total",
                    "value": analysis.overdue_balance,
                    "money": True,
                    "risk": True,
                },
                {"label": "Cuotas", "value": analysis.overdue_count},
                {"label": "Clientes", "value": analysis.clients_overdue},
            ],
            "empty": "Sin morosidad.",
        }

    if key_n == "renovaciones":
        rows = []
        for ren in (
            session.query(RenewalOpportunity)
            .filter_by(organization_id=organization_id)
            .order_by(RenewalOpportunity.target_date)
            .all()
        ):
            pol = session.get(Policy, ren.previous_policy_id)
            party = session.get(Party, pol.client_party_id) if pol else None
            carrier = session.get(Carrier, pol.carrier_id) if pol else None
            line = session.get(InsuranceLine, pol.insurance_line_id) if pol else None
            rows.append(
                {
                    "status": ren.status,
                    "target": ren.target_date.isoformat() if ren.target_date else "—",
                    "policy": pol.policy_number if pol else "—",
                    "client": _party_name(party) or "—",
                    "carrier": carrier.name if carrier else "—",
                    "line": line.code if line else "—",
                }
            )
        return {
            "key": key_n,
            "title": "Reporte de renovaciones",
            "subtitle": "Oportunidades de renovación",
            "columns": [
                {"key": "status", "label": "Estado"},
                {"key": "target", "label": "Fecha", "mono": True},
                {"key": "policy", "label": "Póliza", "mono": True},
                {"key": "client", "label": "Cliente"},
                {"key": "carrier", "label": "Cia"},
                {"key": "line", "label": "Ramo", "mono": True},
            ],
            "rows": rows,
            "kpis": [{"label": "Oportunidades", "value": len(rows)}],
            "empty": "Sin renovaciones.",
        }

    if key_n == "pagos":
        month_start = today.replace(day=1)
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
        rows = []
        total = Decimal("0")
        for pay in pays:
            pol = session.get(Policy, pay.policy_id)
            party = session.get(Party, pol.client_party_id) if pol else None
            total += pay.amount or Decimal("0")
            rows.append(
                {
                    "date": pay.payment_date.isoformat() if pay.payment_date else "—",
                    "amount": pay.amount,
                    "method": pay.method or "—",
                    "reference": pay.reference or "—",
                    "policy": pol.policy_number if pol else "—",
                    "client": _party_name(party) or "—",
                }
            )
        return {
            "key": key_n,
            "title": "Reporte de pagos del mes",
            "subtitle": f"Recaudación {month_start.isoformat()} → {today.isoformat()}",
            "columns": [
                {"key": "date", "label": "Fecha", "mono": True},
                {"key": "policy", "label": "Póliza", "mono": True},
                {"key": "client", "label": "Cliente"},
                {"key": "method", "label": "Método"},
                {"key": "reference", "label": "Referencia", "mono": True},
                {"key": "amount", "label": "Monto", "money": True},
            ],
            "rows": rows,
            "kpis": [
                {"label": "Movimientos", "value": len(rows)},
                {"label": "Total recaudado", "value": total, "money": True},
            ],
            "empty": "Sin pagos en el período.",
        }

    if key_n == "comisiones":
        from corredores.domain.models import CommissionSplit

        rows = []
        cia_total = Decimal("0")
        for c in (
            session.query(Commission)
            .filter_by(organization_id=organization_id)
            .order_by(Commission.calculated_at.desc())
            .all()
        ):
            pol = session.get(Policy, c.policy_id)
            party = session.get(Party, pol.client_party_id) if pol else None
            sp = session.query(CommissionSplit).filter_by(commission_id=c.id).first()
            cia_total += c.calculated_amount or Decimal("0")
            rows.append(
                {
                    "policy": pol.policy_number if pol else "—",
                    "client": _party_name(party) or "—",
                    "base": c.base_amount,
                    "rate": str(c.rate) if c.rate is not None else "—",
                    "cia": c.calculated_amount,
                    "broker": sp.broker_amount if sp else None,
                    "executive": sp.executive_amount if sp else None,
                    "office": sp.office_amount if sp else None,
                    "referral": sp.referral_amount if sp else None,
                    "at": c.calculated_at.date().isoformat() if c.calculated_at else "—",
                }
            )
        return {
            "key": key_n,
            "title": "Reporte de comisiones",
            "subtitle": "Comisión cia + split interno",
            "columns": [
                {"key": "policy", "label": "Póliza", "mono": True},
                {"key": "client", "label": "Cliente"},
                {"key": "base", "label": "Base", "money": True},
                {"key": "rate", "label": "Tasa", "mono": True},
                {"key": "cia", "label": "Cia", "money": True},
                {"key": "broker", "label": "Agente", "money": True},
                {"key": "executive", "label": "Ejec.", "money": True},
                {"key": "office", "label": "Oficina", "money": True},
                {"key": "referral", "label": "Ref.", "money": True},
                {"key": "at", "label": "Fecha", "mono": True},
            ],
            "rows": rows,
            "kpis": [
                {"label": "Comisiones", "value": len(rows)},
                {"label": "Total cia", "value": cia_total, "money": True},
            ],
            "empty": "Sin comisiones calculadas.",
        }

    if key_n == "cotizaciones":
        from corredores.domain.models import QuoteRequest
        from corredores.services.quote_orchestrator import build_comparator

        rows = []
        for qr in (
            session.query(QuoteRequest)
            .filter_by(organization_id=organization_id)
            .order_by(QuoteRequest.created_at.desc())
            .all()
        ):
            line = session.get(InsuranceLine, qr.insurance_line_id)
            try:
                comps = build_comparator(session, qr.id)
            except Exception:
                comps = []
            if not comps:
                rows.append(
                    {
                        "request": qr.id[:8],
                        "line": line.code if line else "—",
                        "created": qr.created_at.date().isoformat() if qr.created_at else "—",
                        "carrier": "—",
                        "source": "—",
                        "status": "EMPTY",
                        "premium": None,
                        "currency": "—",
                    }
                )
                continue
            for r in comps:
                rows.append(
                    {
                        "request": qr.id[:8],
                        "line": line.code if line else "—",
                        "created": qr.created_at.date().isoformat() if qr.created_at else "—",
                        "carrier": r.carrier_name or "—",
                        "source": r.source or "—",
                        "status": r.status or "—",
                        "premium": r.premium,
                        "currency": r.currency or "—",
                    }
                )
        return {
            "key": key_n,
            "title": "Reporte de cotizaciones",
            "subtitle": "Pedidos y primas por aseguradora",
            "columns": [
                {"key": "request", "label": "Pedido", "mono": True},
                {"key": "line", "label": "Ramo", "mono": True},
                {"key": "created", "label": "Creado", "mono": True},
                {"key": "carrier", "label": "Cia"},
                {"key": "source", "label": "Fuente"},
                {"key": "status", "label": "Estado"},
                {"key": "premium", "label": "Prima", "money": True},
                {"key": "currency", "label": "Moneda", "mono": True},
            ],
            "rows": rows,
            "kpis": [{"label": "Líneas", "value": len(rows)}],
            "empty": "Sin cotizaciones.",
        }

    if key_n == "clientes":
        parties = (
            session.query(Party)
            .filter_by(organization_id=organization_id)
            .order_by(Party.created_at.desc())
            .all()
        )
        rows = []
        for p in parties:
            rows.append(
                {
                    "tipo": p.party_type or "—",
                    "nombre": _party_name(p) or "—",
                    "id": p.national_id or "—",
                    "phone": p.phone or "—",
                    "email": p.email or "—",
                    "district": p.district or "—",
                }
            )
        return {
            "key": key_n,
            "title": "Reporte de clientes",
            "subtitle": "Directorio de la correduría",
            "columns": [
                {"key": "tipo", "label": "Tipo"},
                {"key": "nombre", "label": "Nombre"},
                {"key": "id", "label": "ID", "mono": True},
                {"key": "phone", "label": "Teléfono", "mono": True},
                {"key": "email", "label": "Email"},
                {"key": "district", "label": "Distrito"},
            ],
            "rows": rows,
            "kpis": [{"label": "Clientes", "value": len(rows)}],
            "empty": "Sin clientes.",
        }

    if key_n == "reclamos":
        from corredores.domain.models import Claim

        claims = (
            session.query(Claim)
            .filter_by(organization_id=organization_id)
            .order_by(Claim.created_at.desc())
            .all()
        )
        rows = []
        for c in claims:
            pol = session.get(Policy, c.policy_id)
            party = session.get(Party, c.party_id) if c.party_id else (
                session.get(Party, pol.client_party_id) if pol else None
            )
            rows.append(
                {
                    "number": c.claim_number or c.id[:8],
                    "status": c.status,
                    "policy": pol.policy_number if pol else "—",
                    "client": _party_name(party) or "—",
                    "loss": c.loss_date.isoformat() if c.loss_date else "—",
                    "source": c.source or "—",
                    "desc": (c.description or "—")[:80],
                }
            )
        return {
            "key": key_n,
            "title": "Reporte de reclamos",
            "subtitle": "Bandeja de siniestros",
            "columns": [
                {"key": "number", "label": "Nº", "mono": True},
                {"key": "status", "label": "Estado"},
                {"key": "policy", "label": "Póliza", "mono": True},
                {"key": "client", "label": "Cliente"},
                {"key": "loss", "label": "Siniestro", "mono": True},
                {"key": "source", "label": "Fuente"},
                {"key": "desc", "label": "Descripción"},
            ],
            "rows": rows,
            "kpis": [{"label": "Reclamos", "value": len(rows)}],
            "empty": "Sin reclamos.",
        }

    if key_n == "oportunidades":
        # CRM = renovaciones abiertas (misma fuente operativa)
        rows = []
        open_status = {
            "UPCOMING",
            "CONTACT_PENDING",
            "CONTACTED",
            "QUOTING",
            "PROPOSAL_SENT",
            "WAITING_CLIENT",
        }
        for ren in (
            session.query(RenewalOpportunity)
            .filter_by(organization_id=organization_id)
            .order_by(RenewalOpportunity.target_date)
            .all()
        ):
            if ren.status not in open_status:
                continue
            pol = session.get(Policy, ren.previous_policy_id)
            party = session.get(Party, pol.client_party_id) if pol else None
            carrier = session.get(Carrier, pol.carrier_id) if pol else None
            rows.append(
                {
                    "status": ren.status,
                    "target": ren.target_date.isoformat() if ren.target_date else "—",
                    "policy": pol.policy_number if pol else "—",
                    "client": _party_name(party) or "—",
                    "carrier": carrier.name if carrier else "—",
                }
            )
        return {
            "key": key_n,
            "title": "Reporte de oportunidades CRM",
            "subtitle": "Cola abierta de renovación / cotización",
            "columns": [
                {"key": "status", "label": "Estado"},
                {"key": "target", "label": "Fecha", "mono": True},
                {"key": "policy", "label": "Póliza", "mono": True},
                {"key": "client", "label": "Cliente"},
                {"key": "carrier", "label": "Cia"},
            ],
            "rows": rows,
            "kpis": [{"label": "Abiertas", "value": len(rows)}],
            "empty": "Sin oportunidades abiertas.",
        }

    if key_n == "metas":
        from corredores.services.carrier_incentives import list_org_plans_with_progress

        rows = []
        confirmed = Decimal("0")
        benefit = Decimal("0")
        for item in list_org_plans_with_progress(session, organization_id):
            plan = item["plan"]
            g = item.get("progress")
            conf = g.confirmed_amount if g else Decimal("0")
            ben = (
                (g.earned_benefit if g and g.benefit_stage == "EARNED" else g.estimated_benefit)
                if g
                else Decimal("0")
            )
            confirmed += conf or Decimal("0")
            benefit += ben or Decimal("0")
            rows.append(
                {
                    "carrier": item.get("carrier_name") or "—",
                    "plan": plan.name,
                    "metric": plan.metric_type,
                    "period": f"{plan.period_start} → {plan.period_end}",
                    "confirmed": conf,
                    "target": g.target_amount if g else None,
                    "pct": f"{g.progress_pct}%" if g and g.progress_pct is not None else "—",
                    "benefit": ben,
                    "status": plan.status,
                }
            )
        return {
            "key": key_n,
            "title": "Reporte de metas / incentivos",
            "subtitle": "Acuerdos con aseguradoras (ADR-009)",
            "columns": [
                {"key": "carrier", "label": "Cia"},
                {"key": "plan", "label": "Plan"},
                {"key": "metric", "label": "Métrica"},
                {"key": "period", "label": "Período", "mono": True},
                {"key": "confirmed", "label": "Confirmado", "money": True},
                {"key": "target", "label": "Meta", "money": True},
                {"key": "pct", "label": "%", "mono": True},
                {"key": "benefit", "label": "Beneficio", "money": True},
                {"key": "status", "label": "Estado"},
            ],
            "rows": rows,
            "kpis": [
                {"label": "Planes", "value": len(rows)},
                {"label": "Confirmado", "value": confirmed, "money": True},
                {"label": "Beneficio", "value": benefit, "money": True},
            ],
            "empty": "Sin planes de incentivo.",
        }

    # referidos
    from corredores.domain.models import CommissionSplit, PartyRole

    ref_roles = (
        session.query(PartyRole)
        .filter_by(organization_id=organization_id, role_type="REFERRER")
        .all()
    )
    rows = []
    for role in ref_roles:
        party = session.get(Party, role.party_id)
        rows.append(
            {
                "nombre": _party_name(party) or "—",
                "id": party.national_id if party else "—",
                "phone": party.phone if party else "—",
                "email": party.email if party else "—",
                "contexto": role.context_type or "GLOBAL",
            }
        )
    ref_amt = Decimal("0")
    for c in session.query(Commission).filter_by(organization_id=organization_id).all():
        sp = session.query(CommissionSplit).filter_by(commission_id=c.id).first()
        if sp and sp.referral_amount:
            ref_amt += sp.referral_amount
    return {
        "key": key_n,
        "title": "Reporte de referidos",
        "subtitle": "Directorio de referidos + total devengado",
        "columns": [
            {"key": "nombre", "label": "Nombre"},
            {"key": "id", "label": "ID", "mono": True},
            {"key": "phone", "label": "Teléfono", "mono": True},
            {"key": "email", "label": "Email"},
            {"key": "contexto", "label": "Contexto"},
        ],
        "rows": rows,
        "kpis": [
            {"label": "Referidos", "value": len(rows)},
            {"label": "Devengado", "value": ref_amt, "money": True},
        ],
        "empty": "Sin referidos en directorio.",
    }
