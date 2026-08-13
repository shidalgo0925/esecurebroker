"""Bandeja de verificación de comprobantes SaaS (transfer / Yappy)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from corredores.domain.models import AuditEvent, Organization, OrgSubscription, SaasPaymentReceipt
from corredores.services.saas_payment_receipts import receipts_root, save_saas_payment_receipt
from corredores.services.saas_signup import activate_subscription, get_subscription

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class ReceiptVerifyError(Exception):
    pass


def create_receipt_report(
    session: Session,
    *,
    organization_id: str,
    subscription_id: str | None,
    plan_code: str,
    method: str,
    payment_reference: str | None,
    amount_usd: int | None,
    filename: str,
    content: bytes,
    content_type: str | None,
    reported_by: str | None,
) -> SaasPaymentReceipt:
    meta = save_saas_payment_receipt(
        organization_id=organization_id,
        method=method,
        filename=filename,
        content=content,
        content_type=content_type,
    )
    row = SaasPaymentReceipt(
        organization_id=organization_id,
        subscription_id=subscription_id,
        plan_code=plan_code,
        method=method,
        payment_reference=(payment_reference or "").strip() or None,
        amount_usd=amount_usd,
        relative_path=meta["relative_path"],
        original_filename=meta["original_filename"],
        content_type=meta.get("content_type"),
        size_bytes=int(meta.get("size_bytes") or 0),
        reported_by=(reported_by or "").strip() or None,
        verification_status=STATUS_PENDING,
    )
    session.add(row)
    session.flush()
    return row


def list_receipts(
    session: Session, *, status: str | None = STATUS_PENDING
) -> list[dict]:
    q = session.query(SaasPaymentReceipt).order_by(SaasPaymentReceipt.created_at.desc())
    if status:
        q = q.filter(SaasPaymentReceipt.verification_status == status)
    rows = q.limit(200).all()
    org_ids = {r.organization_id for r in rows}
    orgs = {
        o.id: o
        for o in session.query(Organization).filter(Organization.id.in_(org_ids)).all()
    } if org_ids else {}
    out: list[dict] = []
    for r in rows:
        org = orgs.get(r.organization_id)
        out.append(
            {
                "id": r.id,
                "organization_id": r.organization_id,
                "org_name": org.name if org else r.organization_id,
                "plan_code": r.plan_code,
                "method": r.method,
                "payment_reference": r.payment_reference,
                "amount_usd": r.amount_usd,
                "original_filename": r.original_filename,
                "reported_by": r.reported_by,
                "verification_status": r.verification_status,
                "created_at": r.created_at,
                "reviewed_at": r.reviewed_at,
                "review_note": r.review_note,
            }
        )
    return out


def get_receipt(session: Session, receipt_id: str) -> SaasPaymentReceipt | None:
    return session.get(SaasPaymentReceipt, receipt_id)


def absolute_receipt_path(row: SaasPaymentReceipt) -> Path:
    root = receipts_root().resolve()
    path = (root / row.relative_path).resolve()
    if not str(path).startswith(str(root)):
        raise ReceiptVerifyError("ruta de comprobante inválida")
    if not path.is_file():
        raise ReceiptVerifyError("archivo de comprobante no encontrado")
    return path


def approve_receipt(
    session: Session,
    *,
    receipt_id: str,
    reviewer_subject_id: str | None,
    note: str | None = None,
) -> SaasPaymentReceipt:
    row = get_receipt(session, receipt_id)
    if row is None:
        raise ReceiptVerifyError("comprobante no encontrado")
    if row.verification_status != STATUS_PENDING:
        raise ReceiptVerifyError("solo se aprueban comprobantes pendientes")

    sub = None
    if row.subscription_id:
        sub = session.get(OrgSubscription, row.subscription_id)
    if sub is None:
        sub = get_subscription(session, row.organization_id)
    if sub is None:
        raise ReceiptVerifyError("suscripción no encontrada")

    activate_subscription(session, sub, provider="bank_manual")
    now = datetime.now(timezone.utc)
    row.verification_status = STATUS_APPROVED
    row.reviewer_subject_id = reviewer_subject_id
    row.reviewed_at = now
    row.review_note = (note or "").strip() or None
    session.add(
        AuditEvent(
            organization_id=row.organization_id,
            actor_id=reviewer_subject_id,
            entity_type="SaasPaymentReceipt",
            entity_id=row.id,
            action="SAAS_PAYMENT_APPROVED",
            detail_json=json.dumps(
                {
                    "method": row.method,
                    "plan_code": row.plan_code,
                    "subscription_id": sub.id,
                    "note": row.review_note,
                    "en1_ack": False,
                    "note_ops": "Activación local bank_manual; ACK comercial EN1 = carril aparte",
                },
                ensure_ascii=False,
            ),
        )
    )
    session.flush()
    return row


def reject_receipt(
    session: Session,
    *,
    receipt_id: str,
    reviewer_subject_id: str | None,
    note: str | None = None,
) -> SaasPaymentReceipt:
    row = get_receipt(session, receipt_id)
    if row is None:
        raise ReceiptVerifyError("comprobante no encontrado")
    if row.verification_status != STATUS_PENDING:
        raise ReceiptVerifyError("solo se rechazan comprobantes pendientes")

    now = datetime.now(timezone.utc)
    row.verification_status = STATUS_REJECTED
    row.reviewer_subject_id = reviewer_subject_id
    row.reviewed_at = now
    row.review_note = (note or "").strip() or None

    sub = get_subscription(session, row.organization_id)
    if sub is not None and sub.status == "pending":
        # Keep pending so they can re-upload; mark canceled only if note says so later.
        pass

    session.add(
        AuditEvent(
            organization_id=row.organization_id,
            actor_id=reviewer_subject_id,
            entity_type="SaasPaymentReceipt",
            entity_id=row.id,
            action="SAAS_PAYMENT_REJECTED",
            detail_json=json.dumps(
                {
                    "method": row.method,
                    "plan_code": row.plan_code,
                    "note": row.review_note,
                },
                ensure_ascii=False,
            ),
        )
    )
    session.flush()
    return row
