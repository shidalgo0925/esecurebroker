from datetime import date
from decimal import Decimal

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.enums import RecommendationDecision
from corredores.services.auto_e2e import run_auto_e2e_demo
from corredores.services.interactions import complete_task, create_task, log_interaction
from corredores.services.radar import build_radar
from corredores.services.recommendations import create_recommendation, decide_recommendation


def setup_module():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)


def test_radar_and_nba_and_interaction():
    today = date(2026, 8, 10)
    with db.SessionLocal() as session:
        result = run_auto_e2e_demo(session, today=today)
        snap = build_radar(session, result.organization_id, today=today, renewal_horizon_days=400)
        assert snap.por_renovar.count >= 1
        assert snap.por_cobrar.amount >= 0

        rec = create_recommendation(
            session,
            organization_id=result.organization_id,
            kind="COLLECTION_CALL",
            subject_type="Policy",
            subject_id=result.policy_id,
            rationale="Cuotas pendientes detectadas en plan",
            evidence={"payment_plan_id": result.payment_plan_id},
            actor_id="system",
        )
        decide_recommendation(
            session, rec, RecommendationDecision.ACCEPTED, actor_id="broker"
        )
        assert rec.decision == RecommendationDecision.ACCEPTED

        inter = log_interaction(
            session,
            organization_id=result.organization_id,
            party_id=result.client_party_id,
            policy_id=result.policy_id,
            summary="Llamada de seguimiento cobranza",
            channel="CALL",
            actor_id="broker",
        )
        task = create_task(
            session,
            organization_id=result.organization_id,
            title="Recontactar cliente",
            party_id=result.client_party_id,
            policy_id=result.policy_id,
            related_type="RecommendationRecord",
            related_id=rec.id,
            actor_id="broker",
        )
        complete_task(session, task, actor_id="broker")
        assert inter.id and task.status == "DONE"
        session.commit()
