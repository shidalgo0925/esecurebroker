"""SaaS bank receipt verification queue."""

from __future__ import annotations

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.domain.models import Organization, OrgSubscription, SaasPaymentReceipt
from corredores.services.saas_receipt_verify import (
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    approve_receipt,
    create_receipt_report,
    list_receipts,
    reject_receipt,
)
from corredores.services.seed_pilot import seed_pilot


def setup_module():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)
    with db.SessionLocal() as session:
        seed_pilot(session)
        session.commit()


def _org_sub(session):
    org = session.query(Organization).order_by(Organization.created_at).first()
    assert org is not None
    sub = (
        session.query(OrgSubscription).filter_by(organization_id=org.id).one_or_none()
    )
    if sub is None:
        sub = OrgSubscription(
            organization_id=org.id, plan_code="oficina", status="pending"
        )
        session.add(sub)
        session.flush()
    else:
        sub.status = "pending"
        sub.plan_code = "oficina"
    return org, sub


def test_create_approve_activates_subscription(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "corredores.services.saas_payment_receipts.receipts_root",
        lambda: tmp_path,
    )
    with db.SessionLocal() as session:
        org, sub = _org_sub(session)
        row = create_receipt_report(
            session,
            organization_id=org.id,
            subscription_id=sub.id,
            plan_code="oficina",
            method="transfer",
            payment_reference="REF-1",
            amount_usd=99,
            filename="comp.pdf",
            content=b"%PDF-1.4 fake",
            content_type="application/pdf",
            reported_by="owner@test.local",
        )
        session.commit()
        rid = row.id

    with db.SessionLocal() as session:
        pending = list_receipts(session, status=STATUS_PENDING)
        assert any(r["id"] == rid for r in pending)
        approve_receipt(session, receipt_id=rid, reviewer_subject_id="platform:ops", note="ok")
        session.commit()

    with db.SessionLocal() as session:
        row = session.get(SaasPaymentReceipt, rid)
        sub = session.get(OrgSubscription, row.subscription_id)
        assert row.verification_status == STATUS_APPROVED
        assert sub.status == "active"
        assert sub.billing_provider == "bank_manual"


def test_reject_keeps_subscription_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "corredores.services.saas_payment_receipts.receipts_root",
        lambda: tmp_path,
    )
    with db.SessionLocal() as session:
        org, sub = _org_sub(session)
        row = create_receipt_report(
            session,
            organization_id=org.id,
            subscription_id=sub.id,
            plan_code="oficina",
            method="yappy",
            payment_reference="Y-9",
            amount_usd=99,
            filename="y.jpg",
            content=b"\xff\xd8\xff fakejpeg",
            content_type="image/jpeg",
            reported_by="owner@test.local",
        )
        session.commit()
        rid = row.id
        sid = sub.id

    with db.SessionLocal() as session:
        reject_receipt(session, receipt_id=rid, reviewer_subject_id="platform:ops", note="malo")
        session.commit()

    with db.SessionLocal() as session:
        row = session.get(SaasPaymentReceipt, rid)
        sub = session.get(OrgSubscription, sid)
        assert row.verification_status == STATUS_REJECTED
        assert sub.status == "pending"
