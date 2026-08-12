"""ADR-007 — seed two isolated organizations for acceptance / tests."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from corredores.services.auto_e2e import run_auto_e2e_demo
from corredores.services.seed_pilot import seed_pilot
from corredores.services.tenant import ensure_membership
from corredores.identity_ids import actor_id_for_username


def seed_multitenant_demo(
    session: Session,
    *,
    today: date | None = None,
) -> dict:
    """Create Correduría Alfa / Beta with distinct users, clients and policies."""
    today = today or date.today()
    seed_pilot(session, org_name="Correduría Alfa")
    seed_pilot(session, org_name="Correduría Beta")
    alfa = run_auto_e2e_demo(session, org_name="Correduría Alfa", today=today, actor_id="seed-alfa")
    beta = run_auto_e2e_demo(session, org_name="Correduría Beta", today=today, actor_id="seed-beta")

    ensure_membership(
        session,
        subject_id=actor_id_for_username("broker-a"),
        organization_id=alfa.organization_id,
        display_name="Usuario Alfa",
        role_code="BROKER",
    )
    ensure_membership(
        session,
        subject_id=actor_id_for_username("broker-b"),
        organization_id=beta.organization_id,
        display_name="Usuario Beta",
        role_code="BROKER",
    )
    # Dual-membership subject for selector UX (optional)
    ensure_membership(
        session,
        subject_id=actor_id_for_username("broker-multi"),
        organization_id=alfa.organization_id,
        display_name="Usuario Multi",
        role_code="BROKER",
    )
    ensure_membership(
        session,
        subject_id=actor_id_for_username("broker-multi"),
        organization_id=beta.organization_id,
        display_name="Usuario Multi",
        role_code="BROKER",
    )

    return {
        "alfa": {
            "organization_id": alfa.organization_id,
            "party_id": alfa.client_party_id,
            "policy_id": alfa.policy_id,
            "username": "broker-a",
        },
        "beta": {
            "organization_id": beta.organization_id,
            "party_id": beta.client_party_id,
            "policy_id": beta.policy_id,
            "username": "broker-b",
        },
    }
