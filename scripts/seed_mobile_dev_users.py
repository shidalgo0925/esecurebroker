#!/usr/bin/env python3
"""Seed persistent Mobile API users + demo portfolio on ESB DEV DB.

DEV ONLY. Never run against PROD.

Password from env ESB_DEV_SEED_PASSWORD (default for local ops only).
Do not bake credentials into the mobile APK or commit real secrets.

Includes ADR-008 F6 producer user (ASSIGNED_PORTFOLIO).
"""

from __future__ import annotations

import os
import sys
from datetime import date

# Allow: PYTHONPATH=/opt/corredores-dev python scripts/seed_mobile_dev_users.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from corredores.db import Base, SessionLocal, engine  # noqa: E402
from corredores.domain import models as _models  # noqa: E402, F401
from corredores.domain.enums import PartyType  # noqa: E402
from corredores.domain.membership_roles import PRODUCER  # noqa: E402
from corredores.domain.models import BrokerAccount, OrgSubscription, Party  # noqa: E402
from corredores.identity_ids import actor_id_for_username  # noqa: E402
from corredores.services.producer_portfolio import (  # noqa: E402
    active_policy_primary,
    assign_policy_primary,
    create_producer_profile,
)
from corredores.services.saas_signup import hash_password  # noqa: E402
from corredores.services.seats import activate_membership  # noqa: E402
from corredores.services.seed_tenants import seed_multitenant_demo  # noqa: E402
from corredores.services.tenant import ensure_membership  # noqa: E402


def main() -> None:
    password = os.environ.get("ESB_DEV_SEED_PASSWORD", "secreto123")
    today = date.today()
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        info = seed_multitenant_demo(session, today=today)
        alfa = info["alfa"]["organization_id"]
        beta = info["beta"]["organization_id"]

        def upsert_account(email: str, display: str, org_id: str, role: str) -> None:
            subj = actor_id_for_username(email)
            acc = session.query(BrokerAccount).filter_by(email=email).one_or_none()
            if acc is None:
                session.add(
                    BrokerAccount(
                        email=email,
                        password_hash=hash_password(password),
                        display_name=display,
                        subject_id=subj,
                        active=True,
                    )
                )
            else:
                acc.password_hash = hash_password(password)
                acc.display_name = display
                acc.active = True
                acc.subject_id = subj
            if role == PRODUCER:
                activate_membership(
                    session,
                    subject_id=subj,
                    organization_id=org_id,
                    display_name=display,
                    role_code=role,
                    enforce_seats=True,
                )
            else:
                ensure_membership(
                    session,
                    subject_id=subj,
                    organization_id=org_id,
                    display_name=display,
                    role_code=role,
                )

        upsert_account("owner.alfa@example.invalid", "Owner Alfa", alfa, "OWNER")
        upsert_account("broker.alfa2@example.invalid", "Broker Alfa", alfa, "BROKER")
        upsert_account("broker.beta@example.invalid", "Broker Beta", beta, "BROKER")
        upsert_account("multi.dev@example.invalid", "Multi Org", alfa, "BROKER")
        ensure_membership(
            session,
            subject_id=actor_id_for_username("multi.dev@example.invalid"),
            organization_id=beta,
            display_name="Multi Org",
            role_code="BROKER",
        )

        # Alfa = Broker/Red so producer_seats are available (F5/F6)
        for oid, plan in ((alfa, "broker_red"), (beta, "oficina")):
            sub = session.query(OrgSubscription).filter_by(organization_id=oid).one_or_none()
            if sub is None:
                session.add(
                    OrgSubscription(
                        organization_id=oid,
                        plan_code=plan,
                        status="active",
                        billing_provider="piloto",
                    )
                )
            else:
                sub.status = "active"
                sub.plan_code = plan

        # F6 producer: profile + membership + PRIMARY on alfa policy
        prod_email = "producer.alfa@example.invalid"
        prod_subj = actor_id_for_username(prod_email)
        party = (
            session.query(Party)
            .filter_by(organization_id=alfa, email=prod_email)
            .one_or_none()
        )
        if party is None:
            party = Party(
                organization_id=alfa,
                party_type=PartyType.PERSON,
                first_name="Prod",
                last_name="Alfa",
                email=prod_email,
            )
            session.add(party)
            session.flush()
        from corredores.domain.models import ProducerProfile

        profile = (
            session.query(ProducerProfile)
            .filter_by(organization_id=alfa, party_id=party.id)
            .one_or_none()
        )
        if profile is None:
            profile = create_producer_profile(
                session,
                organization_id=alfa,
                party_id=party.id,
                code="PRODALFA",
                display_name="Producer Alfa",
            )
        upsert_account(prod_email, "Producer Alfa", alfa, PRODUCER)
        cur = active_policy_primary(
            session, organization_id=alfa, policy_id=info["alfa"]["policy_id"]
        )
        if cur is None or cur.producer_profile_id != profile.id:
            assign_policy_primary(
                session,
                organization_id=alfa,
                producer_profile_id=profile.id,
                policy_id=info["alfa"]["policy_id"],
                reason="seed F6 producer portfolio",
                assigned_by_subject_id=prod_subj,
            )

        session.commit()
        print("seeded mobile DEV users (password via ESB_DEV_SEED_PASSWORD)")
        print("alfa", alfa, "plan=broker_red")
        print("beta", beta, "plan=oficina")
        print("producer", prod_email, "profile", profile.id)


if __name__ == "__main__":
    main()
