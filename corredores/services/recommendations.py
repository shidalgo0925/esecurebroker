"""Recommendation / NBA lifecycle — never Domain Truth for money or policy state."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from corredores.domain.enums import RecommendationDecision
from corredores.domain.models import AuditEvent, RecommendationRecord


def create_recommendation(
    session: Session,
    *,
    organization_id: str,
    kind: str,
    subject_type: str,
    subject_id: str,
    rationale: str,
    evidence: dict | None = None,
    actor_id: str | None = None,
) -> RecommendationRecord:
    rec = RecommendationRecord(
        organization_id=organization_id,
        kind=kind,
        subject_type=subject_type,
        subject_id=subject_id,
        rationale=rationale,
        evidence_json=json.dumps(evidence or {}, ensure_ascii=False),
    )
    session.add(rec)
    session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="RecommendationRecord",
            entity_id=rec.id,
            action="CREATED",
            detail_json=json.dumps({"kind": kind, "rationale": rationale}),
        )
    )
    session.flush()
    return rec


def decide_recommendation(
    session: Session,
    rec: RecommendationRecord,
    decision: str,
    *,
    actor_id: str | None = None,
) -> RecommendationRecord:
    if decision not in (
        RecommendationDecision.ACCEPTED,
        RecommendationDecision.DISCARDED,
        RecommendationDecision.POSTPONED,
    ):
        raise ValueError(f"invalid decision {decision}")
    if rec.decision is not None:
        raise ValueError("recommendation already decided")
    rec.decision = decision
    rec.decided_at = datetime.now(timezone.utc)
    rec.decided_by = actor_id
    session.add(
        AuditEvent(
            organization_id=rec.organization_id,
            actor_id=actor_id,
            entity_type="RecommendationRecord",
            entity_id=rec.id,
            action=f"DECISION_{decision}",
            detail_json="{}",
        )
    )
    session.flush()
    return rec
