#!/usr/bin/env python3
"""Seed persistent Mobile API users + demo portfolio on ESB DEV DB.

DEV ONLY. Never run against PROD.

Password from env ESB_DEV_SEED_PASSWORD (default for local ops only).
Do not bake credentials into the mobile APK or commit real secrets.
"""

from __future__ import annotations

import os
import sys
from datetime import date

# Allow: PYTHONPATH=/opt/corredores-dev python scripts/seed_mobile_dev_users.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from corredores.db import Base, SessionLocal, engine  # noqa: E402
from corredores.domain import models as _models  # noqa: E402, F401
from corredores.domain.models import BrokerAccount, OrgSubscription  # noqa: E402
from corredores.identity_ids import actor_id_for_username  # noqa: E402
from corredores.services.saas_signup import hash_password  # noqa: E402
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

        for oid in (alfa, beta):
            sub = session.query(OrgSubscription).filter_by(organization_id=oid).one_or_none()
            if sub is None:
                session.add(
                    OrgSubscription(
                        organization_id=oid,
                        plan_code="oficina",
                        status="active",
                        billing_provider="piloto",
                    )
                )
            else:
                sub.status = "active"
                sub.plan_code = "oficina"

        session.commit()
        print("seeded mobile DEV users (password via ESB_DEV_SEED_PASSWORD)")
        print("alfa", alfa)
        print("beta", beta)


if __name__ == "__main__":
    main()
