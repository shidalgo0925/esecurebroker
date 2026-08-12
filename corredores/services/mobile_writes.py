"""ESB GO F5A — activities + document upload (reuse Interaction/Document).

Idempotency via client_activity_id / client_upload_id (per organization).
Authz: AccessContext permissions + entity in scope (ADR-008).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from corredores.domain.enums import DataSource
from corredores.domain.models import AuditEvent, Document, Interaction, Policy
from corredores.services.access_control import (
    AccessContext,
    AccessDenied,
    require_party_in_scope,
    require_permission,
    require_policy_in_scope,
)
from corredores.services.documents import DOC_KINDS, save_party_pdf
from corredores.services.interactions import log_interaction

ACTIVITY_TYPES = frozenset(
    {"NOTE", "CALL", "EMAIL", "WHATSAPP", "VISIT", "OTHER"}
)

IdempotencyResult = Literal["created", "replayed"]


class MobileWriteError(ValueError):
    def __init__(self, code: str, message: str, *, conflict: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.conflict = conflict


@dataclass
class ActivityResult:
    interaction: Interaction
    idempotency: IdempotencyResult


@dataclass
class UploadResult:
    document: Document
    idempotency: IdempotencyResult
    status: str = "SYNCED"


def _require_customer_context(
    session: Session,
    ctx: AccessContext,
    *,
    customer_id: str,
    policy_id: str | None,
) -> tuple[str, str | None]:
    """Validate customer (+ optional policy) in AccessContext scope."""
    party = require_party_in_scope(session, ctx, customer_id)
    if not policy_id:
        return party.id, None
    pol = require_policy_in_scope(session, ctx, policy_id)
    if pol.client_party_id and pol.client_party_id != party.id:
        raise AccessDenied("not found", not_found=True)
    return party.id, pol.id


def list_activities(
    session: Session,
    ctx: AccessContext,
    *,
    customer_id: str | None = None,
    policy_id: str | None = None,
    limit: int = 50,
) -> list[Interaction]:
    require_permission(ctx, "activities:read")
    q = session.query(Interaction).filter_by(organization_id=ctx.organization_id)
    if customer_id:
        require_party_in_scope(session, ctx, customer_id)
        q = q.filter_by(party_id=customer_id)
    if policy_id:
        require_policy_in_scope(session, ctx, policy_id)
        q = q.filter_by(policy_id=policy_id)
    if ctx.scope == "ASSIGNED_PORTFOLIO":
        # Restrict to in-scope parties/policies even without filter
        from corredores.services.access_control import scope_allowlists

        pids, party_ids = scope_allowlists(session, ctx)
        if party_ids is not None:
            if not party_ids:
                return []
            q = q.filter(Interaction.party_id.in_(list(party_ids)))
        if pids is not None and policy_id is None:
            # allow activities with null policy or policy in portfolio
            from sqlalchemy import or_

            if pids:
                q = q.filter(
                    or_(
                        Interaction.policy_id.is_(None),
                        Interaction.policy_id.in_(list(pids)),
                    )
                )
            else:
                q = q.filter(Interaction.policy_id.is_(None))
    return q.order_by(Interaction.created_at.desc()).limit(max(1, min(limit, 100))).all()


def get_activity(session: Session, ctx: AccessContext, activity_id: str) -> Interaction:
    require_permission(ctx, "activities:read")
    row = session.get(Interaction, activity_id)
    if row is None or row.organization_id != ctx.organization_id:
        raise AccessDenied("not found", not_found=True)
    if row.party_id:
        require_party_in_scope(session, ctx, row.party_id)
    elif ctx.scope == "ASSIGNED_PORTFOLIO":
        raise AccessDenied("not found", not_found=True)
    if row.policy_id:
        require_policy_in_scope(session, ctx, row.policy_id)
    return row


def create_activity(
    session: Session,
    ctx: AccessContext,
    *,
    customer_id: str,
    note: str,
    activity_type: str = "NOTE",
    policy_id: str | None = None,
    client_activity_id: str | None = None,
) -> ActivityResult:
    require_permission(ctx, "activities:create")
    party_id, pol_id = _require_customer_context(
        session, ctx, customer_id=customer_id, policy_id=policy_id
    )
    summary = (note or "").strip()
    if not summary:
        raise MobileWriteError("validation_error", "note is required")
    if len(summary) > 4000:
        raise MobileWriteError("validation_error", "note too long")
    channel = (activity_type or "NOTE").strip().upper()
    if channel not in ACTIVITY_TYPES:
        raise MobileWriteError(
            "validation_error",
            f"activity_type must be one of {sorted(ACTIVITY_TYPES)}",
        )
    cid = (client_activity_id or "").strip() or None
    if cid:
        if len(cid) > 128:
            raise MobileWriteError("validation_error", "client_activity_id too long")
        existing = (
            session.query(Interaction)
            .filter_by(organization_id=ctx.organization_id, client_activity_id=cid)
            .one_or_none()
        )
        if existing is not None:
            same = (
                existing.party_id == party_id
                and (existing.policy_id or None) == (pol_id or None)
                and (existing.channel or "").upper() == channel
                and (existing.summary or "") == summary
            )
            if not same:
                raise MobileWriteError(
                    "idempotency_conflict",
                    "client_activity_id already used with different payload",
                    conflict=True,
                )
            return ActivityResult(interaction=existing, idempotency="replayed")

    row = log_interaction(
        session,
        organization_id=ctx.organization_id,
        summary=summary,
        channel=channel,
        party_id=party_id,
        policy_id=pol_id,
        actor_id=ctx.subject_id,
        data_source=DataSource.MANUAL,
    )
    if cid:
        row.client_activity_id = cid
        session.flush()
    return ActivityResult(interaction=row, idempotency="created")


def list_documents(
    session: Session,
    ctx: AccessContext,
    *,
    customer_id: str,
    limit: int = 50,
) -> list[Document]:
    require_permission(ctx, "documents:read")
    require_party_in_scope(session, ctx, customer_id)
    return (
        session.query(Document)
        .filter_by(organization_id=ctx.organization_id, party_id=customer_id)
        .order_by(Document.created_at.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )


def get_document(session: Session, ctx: AccessContext, document_id: str) -> Document:
    require_permission(ctx, "documents:read")
    doc = session.get(Document, document_id)
    if doc is None or doc.organization_id != ctx.organization_id:
        raise AccessDenied("not found", not_found=True)
    if not doc.party_id:
        raise AccessDenied("not found", not_found=True)
    require_party_in_scope(session, ctx, doc.party_id)
    if doc.policy_id:
        require_policy_in_scope(session, ctx, doc.policy_id)
    return doc


def upload_document(
    session: Session,
    ctx: AccessContext,
    *,
    customer_id: str,
    filename: str,
    content: bytes,
    client_upload_id: str,
    content_type: str | None = None,
    policy_id: str | None = None,
    document_type: str = "OTRO",
    title: str | None = None,
) -> UploadResult:
    require_permission(ctx, "documents:manage")
    party_id, pol_id = _require_customer_context(
        session, ctx, customer_id=customer_id, policy_id=policy_id
    )
    cuid = (client_upload_id or "").strip()
    if not cuid:
        raise MobileWriteError("validation_error", "client_upload_id is required")
    if len(cuid) > 128:
        raise MobileWriteError("validation_error", "client_upload_id too long")
    kind = (document_type or "OTRO").strip().upper()
    if kind not in DOC_KINDS:
        raise MobileWriteError(
            "validation_error",
            f"document_type must be one of {list(DOC_KINDS)}",
        )
    digest = hashlib.sha256(content or b"").hexdigest()

    existing = (
        session.query(Document)
        .filter_by(organization_id=ctx.organization_id, client_upload_id=cuid)
        .one_or_none()
    )
    if existing is not None:
        same = (
            existing.party_id == party_id
            and (existing.policy_id or None) == (pol_id or None)
            and (existing.doc_kind or "").upper() == kind
            and (existing.content_sha256 or "") == digest
        )
        if not same:
            raise MobileWriteError(
                "idempotency_conflict",
                "client_upload_id already used with different file or context",
                conflict=True,
            )
        return UploadResult(document=existing, idempotency="replayed", status="SYNCED")

    doc = save_party_pdf(
        session,
        organization_id=ctx.organization_id,
        party_id=party_id,
        filename=filename,
        content=content,
        content_type=content_type,
        title=title,
        doc_kind=kind,
        policy_id=pol_id,
        actor_id=ctx.subject_id,
    )
    doc.client_upload_id = cuid
    doc.content_sha256 = digest
    session.flush()
    return UploadResult(document=doc, idempotency="created", status="SYNCED")


def activity_public_dict(row: Interaction) -> dict[str, Any]:
    return {
        "id": row.id,
        "customer_id": row.party_id,
        "policy_id": row.policy_id,
        "activity_type": row.channel,
        "note": row.summary,
        "actor_id": row.actor_id,
        "client_activity_id": row.client_activity_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "status": "SYNCED",
    }


def document_public_dict(doc: Document, *, idempotency: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "document_id": doc.id,
        "status": "SYNCED",
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "title": doc.title,
        "document_type": doc.doc_kind,
        "original_filename": doc.original_filename,
        "content_type": doc.content_type,
        "size_bytes": doc.size_bytes,
        "context": {
            "customer_id": doc.party_id,
            "policy_id": doc.policy_id,
            "document_type": doc.doc_kind,
            "client_upload_id": doc.client_upload_id,
        },
    }
    if idempotency is not None:
        out["idempotency"] = idempotency
    return out
