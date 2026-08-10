"""Commission calculation with immutable snapshot fields (D-18)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from corredores.domain.enums import CalculationBase
from corredores.domain.models import Commission, CommissionRule, Policy


def resolve_base_amount(policy: Policy, calculation_base: str) -> Decimal:
    mapping = {
        CalculationBase.NET_PREMIUM: policy.net_premium,
        CalculationBase.GROSS_PREMIUM: policy.gross_premium,
        CalculationBase.ANNUAL_PREMIUM: policy.annual_premium,
        CalculationBase.COLLECTED_PREMIUM: None,  # requires payments aggregation — caller supplies
        CalculationBase.FIXED_AMOUNT: None,
        CalculationBase.OTHER: None,
    }
    amount = mapping.get(calculation_base)
    if amount is None:
        raise ValueError(f"calculation_base {calculation_base} requires explicit base_amount")
    return Decimal(amount)


def build_commission(
    *,
    organization_id: str,
    policy: Policy,
    rule: CommissionRule,
    base_amount: Decimal | None = None,
) -> Commission:
    base = base_amount if base_amount is not None else resolve_base_amount(policy, rule.calculation_base)
    rate = Decimal(rule.rate)
    calculated = (base * rate).quantize(Decimal("0.01"))
    return Commission(
        organization_id=organization_id,
        policy_id=policy.id,
        rule_id=rule.id,
        calculation_base=rule.calculation_base,
        base_amount=base,
        rate=rate,
        calculated_amount=calculated,
        calculated_at=datetime.now(timezone.utc),
    )
