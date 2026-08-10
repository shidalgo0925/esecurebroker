"""Cobranza board — 5 UX bands from Domain Truth (not a second ledger)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.enums import CollectionBand, PaymentPromiseStatus
from corredores.domain.models import Installment, Party, PaymentPlan, PaymentPromise, Policy
from corredores.services.collection_bands import classify_collection_band, promise_is_broken
from corredores.services.installment_status import (
    derive_installment_status,
    outstanding_balance,
)


@dataclass
class CobranzaRow:
    band: str
    policy_id: str
    policy_number: str | None
    party_id: str
    party_name: str
    installment_id: str
    installment_number: int
    due_date: date
    amount: Decimal
    balance: Decimal
    status: str
    promise_id: str | None = None


@dataclass
class CobranzaBoard:
    as_of: date
    bands: dict[str, list[CobranzaRow]] = field(default_factory=dict)
    totals: dict[str, Decimal] = field(default_factory=dict)


def _party_name(p: Party | None) -> str:
    if p is None:
        return "—"
    if p.party_type == "ORGANIZATION":
        return p.legal_name or p.trade_name or p.id
    return " ".join(x for x in [p.first_name or "", p.last_name or ""] if x).strip() or p.id


def build_cobranza_board(
    session: Session,
    organization_id: str,
    *,
    today: date | None = None,
) -> CobranzaBoard:
    today = today or date.today()
    board = CobranzaBoard(as_of=today)
    for key in CollectionBand:
        board.bands[key.value] = []
        board.totals[key.value] = Decimal("0")

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
            status = derive_installment_status(inst, today)
            if bal <= 0:
                continue
            active = (
                session.query(PaymentPromise)
                .filter_by(
                    organization_id=organization_id,
                    installment_id=inst.id,
                    status=PaymentPromiseStatus.ACTIVE,
                )
                .first()
            )
            broken_row = (
                session.query(PaymentPromise)
                .filter_by(
                    organization_id=organization_id,
                    installment_id=inst.id,
                    status=PaymentPromiseStatus.BROKEN,
                )
                .first()
            )
            if active and promise_is_broken(active, today=today):
                broken_row = active
                active = None
            band = classify_collection_band(
                inst,
                active_promise=active,
                broken_promise=broken_row,
                today=today,
            )
            row = CobranzaRow(
                band=band.value,
                policy_id=policy.id,
                policy_number=policy.policy_number,
                party_id=policy.client_party_id,
                party_name=_party_name(party),
                installment_id=inst.id,
                installment_number=inst.installment_number,
                due_date=inst.due_date,
                amount=inst.amount,
                balance=bal,
                status=status.value,
                promise_id=(active or broken_row).id if (active or broken_row) else None,
            )
            board.bands[band.value].append(row)
            board.totals[band.value] += bal
    return board
