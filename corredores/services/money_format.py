"""Display formatting for money amounts (UI / PDF)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def format_money(value: object) -> str:
    """Format as 1,234.56 (comma thousands, two decimals)."""
    if value is None or value == "":
        return "0.00"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "0.00"
    return format(amount, ",.2f")
