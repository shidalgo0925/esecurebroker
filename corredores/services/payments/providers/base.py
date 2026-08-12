from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderChargeResult:
    ok: bool
    payment_id: str | None
    status: str
    method: str
    metadata: dict[str, Any]


class PaymentProvider(Protocol):
    method: str

    def charge(self, **kwargs: Any) -> ProviderChargeResult: ...
