from datetime import date

from corredores.db import Base, SessionLocal, engine
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.enums import ClaimStatus, CoverageKnowledgeState
from corredores.services.auto_e2e import run_auto_e2e_demo
from corredores.services.claims import advance_claim, open_claim
from corredores.services.client_360 import build_client_360


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_client_360_and_claim():
    today = date(2026, 8, 10)
    with SessionLocal() as session:
        result = run_auto_e2e_demo(session, today=today)
        snap = build_client_360(session, result.organization_id, result.client_party_id, today=today)
        assert snap.party_id == result.client_party_id
        assert len(snap.policies) >= 1
        assert any(g.state == CoverageKnowledgeState.INSURED_WITH_US.value for g in snap.gaps)

        claim = open_claim(
            session,
            organization_id=result.organization_id,
            policy_id=result.policy_id,
            party_id=result.client_party_id,
            source="PORTAL",
        )
        assert claim.status == ClaimStatus.REPORTED
        advance_claim(session, claim, ClaimStatus.DOCUMENTS_PENDING)
        assert claim.status == ClaimStatus.DOCUMENTS_PENDING
        try:
            advance_claim(session, claim, ClaimStatus.SETTLED)
            assert False, "invalid transition should fail"
        except ValueError:
            pass
        session.commit()
