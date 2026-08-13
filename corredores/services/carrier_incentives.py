"""ADR-009 — Carrier Incentive Plans: CRUD, calculation, settlement (DEV).

Distinct from ordinary CommissionRule. Benefit stages ESTIMATED/EARNED never
auto-promote to RECOGNIZED/PAID.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session

from corredores.domain.incentive_constants import (
    BENEFIT_EARNED,
    BENEFIT_ESTIMATED,
    BENEFIT_FIXED,
    BENEFIT_PERCENTAGE,
    BENEFIT_TYPES,
    CALCULATION_BASES,
    METRIC_TYPES,
    PERIOD_TYPES,
    PLAN_ACTIVE,
    PLAN_DRAFT,
    PLAN_STATUSES,
    SCOPE_AGENT_CODE,
    SCOPE_CARRIER,
    SCOPE_KINDS,
    SCOPE_LINE,
    SCOPE_PRODUCT,
    SETTLE_CALCULATED,
    SETTLE_CLAIMED,
    SETTLE_PAID,
    SETTLE_PARTIALLY_PAID,
    SETTLE_RECOGNIZED,
    SETTLEMENT_CLOSED,
    TXN_CONFIRMED,
    TXN_PENDING,
    TXN_REVERSED,
)
from corredores.domain.models import (
    AuditEvent,
    Carrier,
    CarrierIncentiveEligibleTxn,
    CarrierIncentiveEvidence,
    CarrierIncentivePlan,
    CarrierIncentiveScope,
    CarrierIncentiveSettlement,
    CarrierIncentiveTier,
    InsuranceLine,
    Payment,
    Policy,
)


class IncentiveError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(v: Decimal | int | float | str) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _audit(
    session: Session,
    *,
    organization_id: str,
    actor_id: str | None,
    entity_type: str,
    entity_id: str,
    action: str,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            detail_json=json.dumps(detail or {}, ensure_ascii=False, default=str),
        )
    )


def get_plan(session: Session, organization_id: str, plan_id: str) -> CarrierIncentivePlan | None:
    row = session.get(CarrierIncentivePlan, plan_id)
    if row is None or row.organization_id != organization_id:
        return None
    return row


def list_plans_for_carrier(
    session: Session, *, organization_id: str, carrier_id: str
) -> list[CarrierIncentivePlan]:
    return (
        session.query(CarrierIncentivePlan)
        .filter_by(organization_id=organization_id, carrier_id=carrier_id)
        .order_by(CarrierIncentivePlan.period_start.desc(), CarrierIncentivePlan.name.asc())
        .all()
    )


def list_active_plans(session: Session, organization_id: str) -> list[CarrierIncentivePlan]:
    return (
        session.query(CarrierIncentivePlan)
        .filter_by(organization_id=organization_id, status=PLAN_ACTIVE)
        .order_by(CarrierIncentivePlan.period_end.asc())
        .all()
    )


def create_plan(
    session: Session,
    *,
    organization_id: str,
    carrier_id: str,
    name: str,
    metric_type: str,
    period_start: date,
    period_end: date,
    calculation_base: str,
    currency: str = "USD",
    period_type: str = "CUSTOM",
    description: str | None = None,
    actor_id: str | None = None,
) -> CarrierIncentivePlan:
    carrier = session.get(Carrier, carrier_id)
    if carrier is None or carrier.organization_id != organization_id:
        raise IncentiveError("aseguradora no encontrada")
    name_n = (name or "").strip()
    if not name_n:
        raise IncentiveError("nombre requerido")
    mt = (metric_type or "").upper()
    if mt not in METRIC_TYPES:
        raise IncentiveError(f"metric_type inválido: {metric_type}")
    base = (calculation_base or "").upper()
    if base not in CALCULATION_BASES:
        raise IncentiveError("calculation_base debe ser explícita y conocida")
    pt = (period_type or "CUSTOM").upper()
    if pt not in PERIOD_TYPES:
        raise IncentiveError("period_type inválido")
    if period_end < period_start:
        raise IncentiveError("period_end debe ser ≥ period_start")
    plan = CarrierIncentivePlan(
        organization_id=organization_id,
        carrier_id=carrier_id,
        name=name_n[:200],
        description=(description or "").strip() or None,
        metric_type=mt,
        period_type=pt,
        period_start=period_start,
        period_end=period_end,
        currency=(currency or "USD").upper()[:8],
        calculation_base=base,
        status=PLAN_DRAFT,
    )
    session.add(plan)
    session.flush()
    # Default scope: whole carrier
    session.add(
        CarrierIncentiveScope(
            organization_id=organization_id,
            plan_id=plan.id,
            scope_kind=SCOPE_CARRIER,
        )
    )
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentivePlan",
        entity_id=plan.id,
        action="INCENTIVE_PLAN_CREATED",
        detail={"name": plan.name, "carrier_id": carrier_id, "metric_type": mt},
    )
    session.flush()
    return plan


def activate_plan(
    session: Session, *, organization_id: str, plan_id: str, actor_id: str | None = None
) -> CarrierIncentivePlan:
    plan = get_plan(session, organization_id, plan_id)
    if plan is None:
        raise IncentiveError("plan no encontrado")
    tiers = list_tiers(session, organization_id, plan_id)
    if not tiers:
        raise IncentiveError("el plan necesita al menos un tramo (tier) antes de activar")
    plan.status = PLAN_ACTIVE
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentivePlan",
        entity_id=plan.id,
        action="INCENTIVE_PLAN_ACTIVATED",
        detail={},
    )
    session.flush()
    return plan


def _assert_plan_editable(session: Session, plan: CarrierIncentivePlan) -> None:
    if plan.conditions_locked:
        raise IncentiveError("condiciones del plan bloqueadas (hay liquidaciones cerradas)")
    closed = (
        session.query(CarrierIncentiveSettlement)
        .filter_by(plan_id=plan.id, closed=True)
        .first()
    )
    if closed:
        raise IncentiveError("no se pueden alterar condiciones: hay liquidaciones cerradas")


def add_scope(
    session: Session,
    *,
    organization_id: str,
    plan_id: str,
    scope_kind: str,
    insurance_line_id: str | None = None,
    carrier_product_id: str | None = None,
    agent_code: str | None = None,
    actor_id: str | None = None,
) -> CarrierIncentiveScope:
    plan = get_plan(session, organization_id, plan_id)
    if plan is None:
        raise IncentiveError("plan no encontrado")
    _assert_plan_editable(session, plan)
    kind = (scope_kind or "").upper()
    if kind not in SCOPE_KINDS:
        raise IncentiveError("scope_kind inválido")
    if kind == SCOPE_LINE and not insurance_line_id:
        raise IncentiveError("insurance_line_id requerido para scope LINE")
    if kind == SCOPE_PRODUCT and not carrier_product_id:
        raise IncentiveError("carrier_product_id requerido para scope PRODUCT")
    if kind == SCOPE_AGENT_CODE and not (agent_code or "").strip():
        raise IncentiveError("agent_code requerido para scope AGENT_CODE")
    if insurance_line_id:
        line = session.get(InsuranceLine, insurance_line_id)
        if line is None:
            raise IncentiveError("ramo no encontrado")
    row = CarrierIncentiveScope(
        organization_id=organization_id,
        plan_id=plan_id,
        scope_kind=kind,
        insurance_line_id=insurance_line_id if kind == SCOPE_LINE else None,
        carrier_product_id=carrier_product_id if kind == SCOPE_PRODUCT else None,
        agent_code=(agent_code or "").strip() or None if kind == SCOPE_AGENT_CODE else None,
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentivePlan",
        entity_id=plan_id,
        action="INCENTIVE_SCOPE_ADDED",
        detail={"scope_kind": kind, "scope_id": row.id},
    )
    return row


def list_tiers(session: Session, organization_id: str, plan_id: str) -> list[CarrierIncentiveTier]:
    return (
        session.query(CarrierIncentiveTier)
        .filter_by(organization_id=organization_id, plan_id=plan_id)
        .order_by(CarrierIncentiveTier.sequence.asc())
        .all()
    )


def add_tier(
    session: Session,
    *,
    organization_id: str,
    plan_id: str,
    threshold_amount: Decimal | str,
    benefit_type: str,
    benefit_value: Decimal | str,
    sequence: int | None = None,
    calculation_base: str | None = None,
    actor_id: str | None = None,
) -> CarrierIncentiveTier:
    plan = get_plan(session, organization_id, plan_id)
    if plan is None:
        raise IncentiveError("plan no encontrado")
    _assert_plan_editable(session, plan)
    bt = (benefit_type or "").upper()
    if bt not in BENEFIT_TYPES:
        raise IncentiveError("benefit_type inválido")
    thr = _money(threshold_amount)
    if thr < 0:
        raise IncentiveError("threshold_amount inválido")
    val = Decimal(str(benefit_value))
    if bt == BENEFIT_PERCENTAGE and (val < 0 or val > 100):
        raise IncentiveError("porcentaje debe estar entre 0 y 100")
    if bt == BENEFIT_FIXED and val < 0:
        raise IncentiveError("bono fijo inválido")
    base = (calculation_base or "").upper() or None
    if base and base not in CALCULATION_BASES:
        raise IncentiveError("calculation_base inválida")
    existing = list_tiers(session, organization_id, plan_id)
    seq = sequence if sequence is not None else (max((t.sequence for t in existing), default=0) + 1)
    row = CarrierIncentiveTier(
        organization_id=organization_id,
        plan_id=plan_id,
        sequence=int(seq),
        threshold_amount=thr,
        benefit_type=bt,
        benefit_value=val,
        calculation_base=base,
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentivePlan",
        entity_id=plan_id,
        action="INCENTIVE_TIER_ADDED",
        detail={
            "tier_id": row.id,
            "threshold": str(thr),
            "benefit_type": bt,
            "benefit_value": str(val),
        },
    )
    return row


def register_eligible_txn(
    session: Session,
    *,
    organization_id: str,
    plan_id: str,
    amount: Decimal | str,
    txn_date: date,
    source_type: str,
    source_id: str,
    carrier_id: str | None = None,
    policy_id: str | None = None,
    payment_id: str | None = None,
    insurance_line_id: str | None = None,
    agent_code: str | None = None,
    carrier_receipt_number: str | None = None,
    confirmation_status: str = TXN_PENDING,
    notes: str | None = None,
    actor_id: str | None = None,
) -> CarrierIncentiveEligibleTxn:
    """Idempotent by (plan_id, source_type, source_id). Default PENDING (not official)."""
    plan = get_plan(session, organization_id, plan_id)
    if plan is None:
        raise IncentiveError("plan no encontrado")
    st = (source_type or "").upper()
    sid = (source_id or "").strip()
    if not st or not sid:
        raise IncentiveError("source_type y source_id requeridos")
    existing = (
        session.query(CarrierIncentiveEligibleTxn)
        .filter_by(plan_id=plan_id, source_type=st, source_id=sid)
        .one_or_none()
    )
    if existing:
        return existing
    status = (confirmation_status or TXN_PENDING).upper()
    if status not in {TXN_PENDING, TXN_CONFIRMED, TXN_REVERSED}:
        raise IncentiveError("confirmation_status inválido")
    cid = carrier_id or plan.carrier_id
    amt = _money(amount)
    row = CarrierIncentiveEligibleTxn(
        organization_id=organization_id,
        plan_id=plan_id,
        policy_id=policy_id,
        payment_id=payment_id,
        insurance_line_id=insurance_line_id,
        carrier_id=cid,
        source_type=st,
        source_id=sid,
        txn_date=txn_date,
        amount=amt,
        currency=plan.currency,
        agent_code=(agent_code or "").strip() or None,
        carrier_receipt_number=(carrier_receipt_number or "").strip() or None,
        confirmation_status=status,
        notes=(notes or "").strip() or None,
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentiveEligibleTxn",
        entity_id=row.id,
        action="INCENTIVE_TXN_REGISTERED",
        detail={"status": status, "amount": str(amt), "source": f"{st}:{sid}"},
    )
    return row


def confirm_eligible_txn(
    session: Session,
    *,
    organization_id: str,
    txn_id: str,
    carrier_receipt_number: str | None = None,
    actor_id: str | None = None,
) -> CarrierIncentiveEligibleTxn:
    row = session.get(CarrierIncentiveEligibleTxn, txn_id)
    if row is None or row.organization_id != organization_id:
        raise IncentiveError("transacción no encontrada")
    if row.confirmation_status == TXN_REVERSED:
        raise IncentiveError("no se puede confirmar una transacción reversada")
    row.confirmation_status = TXN_CONFIRMED
    if carrier_receipt_number:
        row.carrier_receipt_number = carrier_receipt_number.strip()
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentiveEligibleTxn",
        entity_id=row.id,
        action="INCENTIVE_TXN_CONFIRMED",
        detail={"receipt": row.carrier_receipt_number},
    )
    session.flush()
    return row


def reverse_eligible_txn(
    session: Session,
    *,
    organization_id: str,
    txn_id: str,
    reason: str,
    actor_id: str | None = None,
) -> CarrierIncentiveEligibleTxn:
    """ORIGINAL → CONFIRMED → REVERSED. Never DELETE."""
    row = session.get(CarrierIncentiveEligibleTxn, txn_id)
    if row is None or row.organization_id != organization_id:
        raise IncentiveError("transacción no encontrada")
    if row.confirmation_status == TXN_REVERSED:
        return row
    row.confirmation_status = TXN_REVERSED
    row.reversed_at = _now()
    row.reverse_reason = (reason or "").strip()[:500] or "reversed"
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentiveEligibleTxn",
        entity_id=row.id,
        action="INCENTIVE_TXN_REVERSED",
        detail={"reason": row.reverse_reason, "amount": str(row.amount)},
    )
    session.flush()
    return row


def register_payment_as_eligible(
    session: Session,
    *,
    organization_id: str,
    plan_id: str,
    payment_id: str,
    confirmation_status: str = TXN_PENDING,
    carrier_receipt_number: str | None = None,
    actor_id: str | None = None,
) -> CarrierIncentiveEligibleTxn:
    pay = session.get(Payment, payment_id)
    if pay is None or pay.organization_id != organization_id:
        raise IncentiveError("pago no encontrado")
    plan = get_plan(session, organization_id, plan_id)
    if plan is None:
        raise IncentiveError("plan no encontrado")
    pol = session.get(Policy, pay.policy_id) if pay.policy_id else None
    if pol and pol.carrier_id != plan.carrier_id:
        raise IncentiveError("el pago no pertenece a la aseguradora del plan")
    return register_eligible_txn(
        session,
        organization_id=organization_id,
        plan_id=plan_id,
        amount=pay.amount,
        txn_date=pay.payment_date,
        source_type="PAYMENT",
        source_id=pay.id,
        carrier_id=plan.carrier_id,
        policy_id=pay.policy_id,
        payment_id=pay.id,
        insurance_line_id=pol.insurance_line_id if pol else None,
        carrier_receipt_number=carrier_receipt_number or pay.reference,
        confirmation_status=confirmation_status,
        actor_id=actor_id,
    )


@dataclass(frozen=True)
class TierHit:
    sequence: int
    threshold_amount: Decimal
    benefit_type: str
    benefit_value: Decimal
    benefit_amount: Decimal


@dataclass(frozen=True)
class PlanProgress:
    plan_id: str
    organization_id: str
    carrier_id: str
    name: str
    metric_type: str
    period_start: date
    period_end: date
    currency: str
    confirmed_amount: Decimal
    pending_amount: Decimal
    target_amount: Decimal | None  # highest tier or primary
    progress_pct: Decimal | None
    remaining: Decimal | None
    benefit_stage: str  # ESTIMATED|EARNED
    estimated_benefit: Decimal
    earned_benefit: Decimal
    active_tier: TierHit | None
    next_tier: CarrierIncentiveTier | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "metric_type": self.metric_type,
            "confirmed_amount": float(self.confirmed_amount),
            "pending_amount": float(self.pending_amount),
            "target_amount": float(self.target_amount) if self.target_amount is not None else None,
            "progress_pct": float(self.progress_pct) if self.progress_pct is not None else None,
            "remaining": float(self.remaining) if self.remaining is not None else None,
            "benefit_stage": self.benefit_stage,
            "estimated_benefit": float(self.estimated_benefit),
            "earned_benefit": float(self.earned_benefit),
            "currency": self.currency,
        }


def _sum_txns(
    session: Session, plan_id: str, *, status: str, period_start: date, period_end: date
) -> Decimal:
    rows = (
        session.query(CarrierIncentiveEligibleTxn)
        .filter_by(plan_id=plan_id, confirmation_status=status)
        .filter(
            CarrierIncentiveEligibleTxn.txn_date >= period_start,
            CarrierIncentiveEligibleTxn.txn_date <= period_end,
        )
        .all()
    )
    return sum((r.amount for r in rows), Decimal("0"))


def _benefit_for_amount(tiers: list[CarrierIncentiveTier], amount: Decimal) -> tuple[Decimal, TierHit | None]:
    """Highest tier whose threshold is met. Percentage applies to confirmed amount (eligible base)."""
    if not tiers:
        return Decimal("0.00"), None
    ordered = sorted(tiers, key=lambda t: (t.threshold_amount, t.sequence))
    hit: CarrierIncentiveTier | None = None
    for t in ordered:
        if amount >= t.threshold_amount:
            hit = t
    if hit is None:
        return Decimal("0.00"), None
    if hit.benefit_type == BENEFIT_FIXED:
        benefit = _money(hit.benefit_value)
    else:
        # PERCENTAGE: benefit_value is percent points (2 → 2%)
        benefit = _money(amount * (hit.benefit_value / Decimal("100")))
    return benefit, TierHit(
        sequence=hit.sequence,
        threshold_amount=hit.threshold_amount,
        benefit_type=hit.benefit_type,
        benefit_value=hit.benefit_value,
        benefit_amount=benefit,
    )


def compute_progress(
    session: Session, *, organization_id: str, plan_id: str
) -> PlanProgress:
    plan = get_plan(session, organization_id, plan_id)
    if plan is None:
        raise IncentiveError("plan no encontrado")
    tiers = list_tiers(session, organization_id, plan_id)
    confirmed = _sum_txns(
        session, plan_id, status=TXN_CONFIRMED, period_start=plan.period_start, period_end=plan.period_end
    )
    pending = _sum_txns(
        session, plan_id, status=TXN_PENDING, period_start=plan.period_start, period_end=plan.period_end
    )
    # Official progress uses CONFIRMED only
    benefit, active = _benefit_for_amount(tiers, confirmed)
    # Estimated also considers pending (informational only)
    est_benefit, _ = _benefit_for_amount(tiers, confirmed + pending)

    target = max((t.threshold_amount for t in tiers), default=None) if tiers else None
    # Prefer first (lowest) unmet tier as "next" target for UX
    next_tier = None
    primary_target = None
    ordered = sorted(tiers, key=lambda t: (t.threshold_amount, t.sequence))
    for t in ordered:
        if confirmed < t.threshold_amount:
            next_tier = t
            primary_target = t.threshold_amount
            break
    if primary_target is None and ordered:
        primary_target = ordered[-1].threshold_amount
        next_tier = None

    progress_pct = None
    remaining = None
    if primary_target and primary_target > 0:
        progress_pct = (confirmed / primary_target * Decimal("100")).quantize(Decimal("0.01"))
        remaining = _money(max(Decimal("0"), primary_target - confirmed))

    earned = benefit if active is not None else Decimal("0.00")
    stage = BENEFIT_EARNED if active is not None else BENEFIT_ESTIMATED
    # If no tier hit, still ESTIMATED with 0; estimated_benefit may use pending for display
    return PlanProgress(
        plan_id=plan.id,
        organization_id=organization_id,
        carrier_id=plan.carrier_id,
        name=plan.name,
        metric_type=plan.metric_type,
        period_start=plan.period_start,
        period_end=plan.period_end,
        currency=plan.currency,
        confirmed_amount=_money(confirmed),
        pending_amount=_money(pending),
        target_amount=_money(primary_target) if primary_target is not None else None,
        progress_pct=progress_pct,
        remaining=remaining,
        benefit_stage=stage if active else BENEFIT_ESTIMATED,
        estimated_benefit=_money(est_benefit),
        earned_benefit=_money(earned),
        active_tier=active,
        next_tier=next_tier,
    )


def upsert_calculated_settlement(
    session: Session,
    *,
    organization_id: str,
    plan_id: str,
    period_label: str | None = None,
    actor_id: str | None = None,
) -> CarrierIncentiveSettlement:
    """Refresh CALCULATED settlement from confirmed progress. Never sets RECOGNIZED/PAID."""
    plan = get_plan(session, organization_id, plan_id)
    if plan is None:
        raise IncentiveError("plan no encontrado")
    progress = compute_progress(session, organization_id=organization_id, plan_id=plan_id)
    label = (period_label or f"{plan.period_start.year}").strip()
    row = (
        session.query(CarrierIncentiveSettlement)
        .filter_by(plan_id=plan_id, period_label=label)
        .one_or_none()
    )
    if row and row.closed:
        raise IncentiveError("liquidación cerrada; no se recalcula en silencio")
    if row and row.status in SETTLEMENT_CLOSED:
        raise IncentiveError("liquidación en estado terminal; no se recalcula")

    stage = progress.benefit_stage
    if row is None:
        row = CarrierIncentiveSettlement(
            organization_id=organization_id,
            plan_id=plan_id,
            period_label=label,
            eligible_amount=progress.confirmed_amount,
            calculated_benefit=progress.earned_benefit
            if stage == BENEFIT_EARNED
            else progress.estimated_benefit,
            benefit_stage=stage,
            status=SETTLE_CALCULATED,
        )
        session.add(row)
        action = "INCENTIVE_SETTLEMENT_CALCULATED"
    else:
        if row.status not in {SETTLE_CALCULATED, SETTLE_CLAIMED}:
            raise IncentiveError(f"no se recalcula settlement en status {row.status}")
        row.eligible_amount = progress.confirmed_amount
        row.calculated_benefit = (
            progress.earned_benefit if stage == BENEFIT_EARNED else progress.estimated_benefit
        )
        row.benefit_stage = stage
        if row.status == SETTLE_CALCULATED:
            pass
        action = "INCENTIVE_SETTLEMENT_RECALCULATED"
    session.flush()
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentiveSettlement",
        entity_id=row.id,
        action=action,
        detail={
            "eligible": str(row.eligible_amount),
            "benefit": str(row.calculated_benefit),
            "stage": row.benefit_stage,
        },
    )
    return row


def mark_claimed(
    session: Session,
    *,
    organization_id: str,
    settlement_id: str,
    claimed_amount: Decimal | str | None = None,
    carrier_reference: str | None = None,
    notes: str | None = None,
    actor_id: str | None = None,
) -> CarrierIncentiveSettlement:
    row = session.get(CarrierIncentiveSettlement, settlement_id)
    if row is None or row.organization_id != organization_id:
        raise IncentiveError("liquidación no encontrada")
    if row.status not in {SETTLE_CALCULATED, SETTLE_CLAIMED}:
        raise IncentiveError("solo se reclama desde CALCULATED")
    row.status = SETTLE_CLAIMED
    row.claimed_amount = _money(claimed_amount if claimed_amount is not None else row.calculated_benefit)
    row.claimed_at = _now()
    if carrier_reference:
        row.carrier_reference = carrier_reference.strip()[:120]
    if notes:
        row.notes = notes.strip()
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentiveSettlement",
        entity_id=row.id,
        action="INCENTIVE_SETTLEMENT_CLAIMED",
        detail={"claimed_amount": str(row.claimed_amount)},
    )
    session.flush()
    return row


def mark_recognized(
    session: Session,
    *,
    organization_id: str,
    settlement_id: str,
    recognized_amount: Decimal | str,
    carrier_reference: str | None = None,
    notes: str | None = None,
    actor_id: str | None = None,
) -> CarrierIncentiveSettlement:
    """Carrier confirmed benefit — never auto from EARNED."""
    row = session.get(CarrierIncentiveSettlement, settlement_id)
    if row is None or row.organization_id != organization_id:
        raise IncentiveError("liquidación no encontrada")
    if row.status not in {SETTLE_CLAIMED, SETTLE_RECOGNIZED}:
        raise IncentiveError("debe estar CLAIMED antes de RECOGNIZED")
    row.status = SETTLE_RECOGNIZED
    row.recognized_amount = _money(recognized_amount)
    row.recognized_at = _now()
    row.closed = True
    plan = session.get(CarrierIncentivePlan, row.plan_id)
    if plan:
        plan.conditions_locked = True
    if carrier_reference:
        row.carrier_reference = carrier_reference.strip()[:120]
    if notes:
        row.notes = ((row.notes or "") + "\n" + notes.strip()).strip()
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentiveSettlement",
        entity_id=row.id,
        action="INCENTIVE_SETTLEMENT_RECOGNIZED",
        detail={"recognized_amount": str(row.recognized_amount)},
    )
    session.flush()
    return row


def mark_paid(
    session: Session,
    *,
    organization_id: str,
    settlement_id: str,
    paid_amount: Decimal | str,
    notes: str | None = None,
    actor_id: str | None = None,
) -> CarrierIncentiveSettlement:
    row = session.get(CarrierIncentiveSettlement, settlement_id)
    if row is None or row.organization_id != organization_id:
        raise IncentiveError("liquidación no encontrada")
    if row.status not in {SETTLE_RECOGNIZED, SETTLE_PARTIALLY_PAID, SETTLE_PAID}:
        raise IncentiveError("debe estar RECOGNIZED antes de PAID")
    paid = _money(paid_amount)
    recognized = row.recognized_amount or Decimal("0")
    row.paid_amount = paid
    row.paid_at = _now()
    if paid < recognized:
        row.status = SETTLE_PARTIALLY_PAID
    else:
        row.status = SETTLE_PAID
    row.closed = True
    if notes:
        row.notes = ((row.notes or "") + "\n" + notes.strip()).strip()
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentiveSettlement",
        entity_id=row.id,
        action="INCENTIVE_SETTLEMENT_PAID",
        detail={"paid_amount": str(paid), "status": row.status},
    )
    session.flush()
    return row


def add_evidence(
    session: Session,
    *,
    organization_id: str,
    plan_id: str,
    title: str,
    evidence_kind: str = "OTRO",
    settlement_id: str | None = None,
    notes: str | None = None,
    actor_id: str | None = None,
) -> CarrierIncentiveEvidence:
    plan = get_plan(session, organization_id, plan_id)
    if plan is None:
        raise IncentiveError("plan no encontrado")
    title_n = (title or "").strip()
    if not title_n:
        raise IncentiveError("título requerido")
    row = CarrierIncentiveEvidence(
        organization_id=organization_id,
        plan_id=plan_id,
        settlement_id=settlement_id,
        evidence_kind=(evidence_kind or "OTRO").upper()[:40],
        title=title_n[:200],
        notes=(notes or "").strip() or None,
        uploaded_by=actor_id,
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        organization_id=organization_id,
        actor_id=actor_id,
        entity_type="CarrierIncentiveEvidence",
        entity_id=row.id,
        action="INCENTIVE_EVIDENCE_ADDED",
        detail={"kind": row.evidence_kind, "title": row.title},
    )
    return row


def hoy_incentive_alerts(session: Session, organization_id: str) -> list[dict[str, Any]]:
    """Operational alerts for Today / Hoy (F5)."""
    alerts: list[dict[str, Any]] = []
    for plan in list_active_plans(session, organization_id):
        try:
            p = compute_progress(session, organization_id=organization_id, plan_id=plan.id)
        except IncentiveError:
            continue
        carrier = session.get(Carrier, plan.carrier_id)
        cname = carrier.name if carrier else plan.carrier_id[:8]
        if p.benefit_stage == BENEFIT_EARNED:
            alerts.append(
                {
                    "kind": "meta_alcanzada",
                    "severity": "warning",
                    "title": f"Meta alcanzada · {p.name}",
                    "body": (
                        f"{cname}: beneficio estimado {p.currency} {p.earned_benefit}. "
                        "Pendiente de gestionar (reclamar / reconocer)."
                    ),
                    "plan_id": plan.id,
                    "carrier_id": plan.carrier_id,
                    "href": f"/aseguradoras/{plan.carrier_id}/beneficios/{plan.id}",
                }
            )
        elif p.remaining is not None and p.progress_pct is not None and p.progress_pct >= Decimal("70"):
            alerts.append(
                {
                    "kind": "meta_proxima",
                    "severity": "info",
                    "title": f"Meta próxima · {p.name}",
                    "body": (
                        f"{cname}: {p.progress_pct}% alcanzado. "
                        f"Faltan {p.currency} {p.remaining} para activar el beneficio."
                    ),
                    "plan_id": plan.id,
                    "carrier_id": plan.carrier_id,
                    "href": f"/aseguradoras/{plan.carrier_id}/beneficios/{plan.id}",
                }
            )
        # Recognized unpaid
        for s in (
            session.query(CarrierIncentiveSettlement)
            .filter_by(organization_id=organization_id, plan_id=plan.id, status=SETTLE_RECOGNIZED)
            .all()
        ):
            alerts.append(
                {
                    "kind": "beneficio_pendiente_pago",
                    "severity": "warning",
                    "title": f"Beneficio reconocido · {p.name}",
                    "body": (
                        f"{cname} reconoció {plan.currency} {s.recognized_amount}. Pendiente de pago."
                    ),
                    "plan_id": plan.id,
                    "carrier_id": plan.carrier_id,
                    "href": f"/aseguradoras/{plan.carrier_id}/beneficios/{plan.id}",
                }
            )
        for s in (
            session.query(CarrierIncentiveSettlement)
            .filter_by(organization_id=organization_id, plan_id=plan.id)
            .filter(CarrierIncentiveSettlement.recognized_amount.isnot(None))
            .all()
        ):
            if s.recognized_amount is None:
                continue
            calc = s.calculated_benefit or Decimal("0")
            if abs(s.recognized_amount - calc) >= Decimal("0.01") and s.status in {
                SETTLE_RECOGNIZED,
                SETTLE_PARTIALLY_PAID,
                SETTLE_PAID,
            }:
                alerts.append(
                    {
                        "kind": "discrepancia",
                        "severity": "danger",
                        "title": f"Discrepancia · {p.name}",
                        "body": (
                            f"ESB calcula {plan.currency} {calc} y la aseguradora reconoce "
                            f"{plan.currency} {s.recognized_amount}. Requiere revisión."
                        ),
                        "plan_id": plan.id,
                        "carrier_id": plan.carrier_id,
                        "href": f"/aseguradoras/{plan.carrier_id}/beneficios/{plan.id}",
                    }
                )
    return alerts
