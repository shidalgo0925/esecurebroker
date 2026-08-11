"""Quote Orchestrator — CONNECTIVITY/SALES backbone without real carrier APIs.

Sources: API (stub), FILE/IMPORT, MANUAL → same NormalizedQuote comparator.
IA must not invent premiums; this layer only records carrier/manual facts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.orm import Session

from corredores.domain.enums import DataSource
from corredores.domain.models import (
    AuditEvent,
    Carrier,
    CarrierQuoteRequest,
    NormalizedQuote,
    QuoteRequest,
)


class QuoteResponseSource(StrEnum):
    API = "API"
    FILE = "FILE"
    MANUAL = "MANUAL"


class CarrierQuoteStatus(StrEnum):
    PENDING = "PENDING"
    RECEIVED_API = "RECEIVED_API"
    RECEIVED_FILE = "RECEIVED_FILE"
    RECEIVED_MANUAL = "RECEIVED_MANUAL"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    NORMALIZED = "NORMALIZED"


@dataclass
class ComparatorRow:
    carrier_id: str
    carrier_code: str
    carrier_name: str
    source: str
    status: str
    premium: Decimal | None
    currency: str
    normalized_quote_id: str | None
    carrier_quote_request_id: str


def create_quote_request(
    session: Session,
    *,
    organization_id: str,
    insurance_line_id: str,
    submission_id: str | None = None,
    payload: dict | None = None,
    actor_id: str | None = None,
) -> QuoteRequest:
    qr = QuoteRequest(
        organization_id=organization_id,
        submission_id=submission_id,
        insurance_line_id=insurance_line_id,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
    )
    session.add(qr)
    session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="QuoteRequest",
            entity_id=qr.id,
            action="CREATED",
            detail_json=qr.payload_json,
        )
    )
    session.flush()
    return qr


def dispatch_carriers(
    session: Session,
    quote_request: QuoteRequest,
    carrier_ids: list[str],
    *,
    actor_id: str | None = None,
) -> list[CarrierQuoteRequest]:
    from corredores.domain.models import Carrier

    rows: list[CarrierQuoteRequest] = []
    for cid in carrier_ids:
        carrier = session.get(Carrier, cid)
        if carrier is None or carrier.organization_id != quote_request.organization_id:
            raise ValueError(f"carrier not in organization: {cid}")
        cqr = CarrierQuoteRequest(
            quote_request_id=quote_request.id,
            carrier_id=cid,
            status=CarrierQuoteStatus.PENDING,
        )
        session.add(cqr)
        rows.append(cqr)
    session.flush()
    session.add(
        AuditEvent(
            organization_id=quote_request.organization_id,
            actor_id=actor_id,
            entity_type="QuoteRequest",
            entity_id=quote_request.id,
            action="DISPATCHED",
            detail_json=json.dumps({"carrier_ids": carrier_ids}),
        )
    )
    session.flush()
    return rows


def _normalize(
    session: Session,
    cqr: CarrierQuoteRequest,
    *,
    premium: Decimal,
    currency: str = "USD",
    source: QuoteResponseSource,
    raw_ref: str | None = None,
    actor_id: str | None = None,
    organization_id: str,
) -> NormalizedQuote:
    status_map = {
        QuoteResponseSource.API: CarrierQuoteStatus.RECEIVED_API,
        QuoteResponseSource.FILE: CarrierQuoteStatus.RECEIVED_FILE,
        QuoteResponseSource.MANUAL: CarrierQuoteStatus.RECEIVED_MANUAL,
    }
    cqr.status = status_map[source]
    session.flush()
    nq = NormalizedQuote(
        carrier_quote_request_id=cqr.id,
        premium=premium,
        currency=currency,
        raw_ref=raw_ref or source.value,
    )
    session.add(nq)
    session.flush()
    cqr.status = CarrierQuoteStatus.NORMALIZED
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="NormalizedQuote",
            entity_id=nq.id,
            action="NORMALIZED",
            detail_json=json.dumps(
                {
                    "source": source.value,
                    "premium": str(premium),
                    "currency": currency,
                    "carrier_quote_request_id": cqr.id,
                }
            ),
        )
    )
    session.flush()
    return nq


def record_manual_quote(
    session: Session,
    cqr: CarrierQuoteRequest,
    *,
    organization_id: str,
    premium: Decimal,
    currency: str = "USD",
    actor_id: str | None = None,
    note: str | None = None,
) -> NormalizedQuote:
    return _normalize(
        session,
        cqr,
        premium=premium,
        currency=currency,
        source=QuoteResponseSource.MANUAL,
        raw_ref=note or "MANUAL",
        actor_id=actor_id,
        organization_id=organization_id,
    )


def record_file_quote(
    session: Session,
    cqr: CarrierQuoteRequest,
    *,
    organization_id: str,
    premium: Decimal,
    currency: str = "USD",
    file_ref: str,
    actor_id: str | None = None,
) -> NormalizedQuote:
    return _normalize(
        session,
        cqr,
        premium=premium,
        currency=currency,
        source=QuoteResponseSource.FILE,
        raw_ref=file_ref,
        actor_id=actor_id,
        organization_id=organization_id,
    )


def record_api_quote_stub(
    session: Session,
    cqr: CarrierQuoteRequest,
    *,
    organization_id: str,
    premium: Decimal,
    currency: str = "USD",
    actor_id: str | None = None,
) -> NormalizedQuote:
    """Stub only — no real HTTP. Marks source=API for comparator parity."""
    return _normalize(
        session,
        cqr,
        premium=premium,
        currency=currency,
        source=QuoteResponseSource.API,
        raw_ref="API_STUB",
        actor_id=actor_id,
        organization_id=organization_id,
    )


def mark_carrier_failed(
    session: Session,
    cqr: CarrierQuoteRequest,
    *,
    organization_id: str,
    reason: str,
    actor_id: str | None = None,
) -> CarrierQuoteRequest:
    cqr.status = CarrierQuoteStatus.FAILED
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="CarrierQuoteRequest",
            entity_id=cqr.id,
            action="FAILED",
            detail_json=json.dumps({"reason": reason}),
        )
    )
    session.flush()
    return cqr


def build_comparator(session: Session, quote_request_id: str) -> list[ComparatorRow]:
    """Single comparator — all sources normalized the same way."""
    cqrs = session.query(CarrierQuoteRequest).filter_by(quote_request_id=quote_request_id).all()
    rows: list[ComparatorRow] = []
    for cqr in cqrs:
        carrier = session.get(Carrier, cqr.carrier_id)
        nq = (
            session.query(NormalizedQuote)
            .filter_by(carrier_quote_request_id=cqr.id)
            .order_by(NormalizedQuote.created_at.desc())
            .first()
        )
        if nq is None:
            source = "PENDING"
        elif nq.raw_ref == "API_STUB":
            source = QuoteResponseSource.API.value
        elif nq.raw_ref and str(nq.raw_ref).startswith("file:"):
            source = QuoteResponseSource.FILE.value
        else:
            source = QuoteResponseSource.MANUAL.value

        rows.append(
            ComparatorRow(
                carrier_id=cqr.carrier_id,
                carrier_code=carrier.code if carrier else "?",
                carrier_name=carrier.name if carrier else "?",
                source=source,
                status=cqr.status,
                premium=nq.premium if nq else None,
                currency=nq.currency if nq else "USD",
                normalized_quote_id=nq.id if nq else None,
                carrier_quote_request_id=cqr.id,
            )
        )
    return rows
