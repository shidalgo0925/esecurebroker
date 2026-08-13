"""ADR-011 F1 — seed default CRM catalogs per Organization.

Idempotent: skips codes that already exist for the org.
Does not create Prospect/Opportunity rows.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from corredores.domain.crm_constants import (
    DEFAULT_LEAD_SOURCES,
    DEFAULT_LOST_REASONS,
    PIPELINE_KANBAN_CODES,
    PIPELINE_STAGE_CODES,
    PIPELINE_STAGE_LABELS_ES,
    STAGE_LOST,
    STAGE_WON,
)
from corredores.domain.models import CrmLeadSource, CrmLostReason, CrmPipelineStage


def ensure_default_crm_catalogs(session: Session, organization_id: str) -> dict[str, int]:
    """Ensure standard lead sources, lost reasons, and pipeline stages exist."""
    created = {"lead_sources": 0, "lost_reasons": 0, "pipeline_stages": 0}

    existing_src = {
        r.code
        for r in session.query(CrmLeadSource).filter_by(organization_id=organization_id).all()
    }
    for i, (code, name) in enumerate(DEFAULT_LEAD_SOURCES, start=1):
        if code in existing_src:
            continue
        session.add(
            CrmLeadSource(
                organization_id=organization_id,
                code=code,
                name=name,
                sort_order=i * 10,
                active=True,
            )
        )
        created["lead_sources"] += 1

    existing_lost = {
        r.code
        for r in session.query(CrmLostReason).filter_by(organization_id=organization_id).all()
    }
    for i, (code, name) in enumerate(DEFAULT_LOST_REASONS, start=1):
        if code in existing_lost:
            continue
        session.add(
            CrmLostReason(
                organization_id=organization_id,
                code=code,
                name=name,
                sort_order=i * 10,
                active=True,
            )
        )
        created["lost_reasons"] += 1

    existing_stages = {
        r.code
        for r in session.query(CrmPipelineStage).filter_by(organization_id=organization_id).all()
    }
    for i, code in enumerate(PIPELINE_STAGE_CODES, start=1):
        if code in existing_stages:
            continue
        session.add(
            CrmPipelineStage(
                organization_id=organization_id,
                code=code,
                name=PIPELINE_STAGE_LABELS_ES.get(code, code),
                sequence=i * 10,
                is_won=(code == STAGE_WON),
                is_lost=(code == STAGE_LOST),
                is_kanban=(code in PIPELINE_KANBAN_CODES),
                active=True,
            )
        )
        created["pipeline_stages"] += 1

    session.flush()
    return created
