#!/usr/bin/env python3
"""P0 certification smoke — domain backbone without UI."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from corredores.db import Base, SessionLocal, engine
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.enums import ClaimStatus, RecommendationDecision
from corredores.services.auto_e2e import run_auto_e2e_demo
from corredores.services.claims import advance_claim, open_claim
from corredores.services.client_360 import build_client_360
from corredores.services.radar import build_radar
from corredores.services.recommendations import create_recommendation, decide_recommendation
from corredores.services.today import build_today_queue


def main() -> int:
    Base.metadata.create_all(bind=engine)
    today = date.today()
    with SessionLocal() as session:
        result = run_auto_e2e_demo(session, today=today)
        c360 = build_client_360(session, result.organization_id, result.client_party_id, today=today)
        radar = build_radar(session, result.organization_id, today=today, renewal_horizon_days=400)
        today_q = build_today_queue(session, result.organization_id, today=today, renewal_horizon_days=400)
        claim = open_claim(
            session,
            organization_id=result.organization_id,
            policy_id=result.policy_id,
            party_id=result.client_party_id,
            description="Demo scratch",
            source="BROKER",
        )
        advance_claim(session, claim, ClaimStatus.DOCUMENTS_PENDING)
        rec = create_recommendation(
            session,
            organization_id=result.organization_id,
            kind="REVIEW_CLAIM",
            subject_type="Claim",
            subject_id=claim.id,
            rationale="Documentos pendientes",
            evidence={"claim_id": claim.id},
        )
        decide_recommendation(session, rec, RecommendationDecision.POSTPONED, actor_id="cert")
        claim_status = claim.status
        nba_decision = rec.decision
        session.commit()

    report = {
        "ok": True,
        "flow": "E2E+360+Radar+Hoy+Claim+NBA",
        "policy_id": result.policy_id,
        "client": c360.display_name,
        "gaps": [{"label": g.label, "state": g.state} for g in c360.gaps],
        "radar_por_renovar": str(radar.por_renovar.amount),
        "today_items": len(today_q),
        "claim_status": claim_status,
        "nba_decision": nba_decision,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
