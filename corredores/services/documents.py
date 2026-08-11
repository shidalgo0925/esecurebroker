"""Client PDF document attachments — metadata in DB, bytes under var/documents."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from corredores.config import settings
from corredores.domain.enums import DataSource
from corredores.domain.models import AuditEvent, Document, Party

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/jpg"}
DOC_KINDS = (
    "CEDULA",
    "RUC",
    "LICENCIA",
    "POLIZA",
    "PAGO",
    "COTIZACION",
    "RECLAMO",
    "OTRO",
)


def documents_root() -> Path:
    root = Path(getattr(settings, "documents_root", "") or "/opt/corredores/var/documents")
    root.mkdir(parents=True, exist_ok=True)
    return root


def party_dir(organization_id: str, party_id: str) -> Path:
    path = documents_root() / organization_id / party_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(name: str) -> str:
    base = Path(name or "documento.pdf").name
    base = re.sub(r"[^\w.\- ()áéíóúñÁÉÍÓÚÑ]+", "_", base, flags=re.UNICODE)
    return base[:200] or "documento.bin"


def _detect_kind(content: bytes, content_type: str | None, filename: str) -> tuple[str, str]:
    """Return (stored_ext_hint, normalized_content_type) or raise."""
    ctype = (content_type or "").split(";")[0].strip().lower()
    name = (filename or "").lower()
    if content.startswith(b"%PDF") or ctype == "application/pdf" or name.endswith(".pdf"):
        if not content.startswith(b"%PDF"):
            raise ValueError("solo se permiten archivos PDF válidos")
        return ".pdf", "application/pdf"
    if content.startswith(b"\xff\xd8\xff") or ctype in {"image/jpeg", "image/jpg"} or name.endswith((".jpg", ".jpeg")):
        return ".jpg", "image/jpeg"
    if content.startswith(b"\x89PNG") or ctype == "image/png" or name.endswith(".png"):
        return ".png", "image/png"
    if (content[:4] == b"RIFF" and b"WEBP" in content[:16]) or ctype == "image/webp" or name.endswith(".webp"):
        return ".webp", "image/webp"
    raise ValueError("solo se permiten PDF o fotos (JPG/PNG/WEBP)")


def save_party_pdf(
    session: Session,
    *,
    organization_id: str,
    party_id: str,
    filename: str,
    content: bytes,
    content_type: str | None = None,
    title: str | None = None,
    doc_kind: str = "OTRO",
    policy_id: str | None = None,
    actor_id: str | None = None,
) -> Document:
    party = session.get(Party, party_id)
    if party is None or party.organization_id != organization_id:
        raise ValueError("cliente no encontrado")
    if not content:
        raise ValueError("archivo vacío")
    if len(content) > MAX_PDF_BYTES:
        raise ValueError("el archivo no puede superar 10 MB")

    ext, norm_ctype = _detect_kind(content, content_type, filename)
    kind = (doc_kind or "OTRO").strip().upper()
    if kind not in DOC_KINDS:
        kind = "OTRO"

    original = _safe_filename(filename)
    if not Path(original).suffix:
        original = f"{original}{ext}"
    stored = f"{uuid.uuid4().hex}{ext}"
    dest = party_dir(organization_id, party_id) / stored
    dest.write_bytes(content)

    doc = Document(
        organization_id=organization_id,
        party_id=party_id,
        policy_id=policy_id or None,
        title=(title or Path(original).stem or "Documento").strip()[:200],
        original_filename=original,
        content_type=norm_ctype,
        stored_name=stored,
        size_bytes=len(content),
        doc_kind=kind,
        uploaded_by=actor_id,
        data_source=DataSource.MANUAL,
    )
    session.add(doc)
    session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="Document",
            entity_id=doc.id,
            action="UPLOADED",
            detail_json=json.dumps(
                {"party_id": party_id, "filename": original, "size": len(content), "kind": kind}
            ),
        )
    )
    session.flush()
    return doc


def list_party_documents(session: Session, *, organization_id: str, party_id: str) -> list[Document]:
    return (
        session.query(Document)
        .filter_by(organization_id=organization_id, party_id=party_id)
        .order_by(Document.created_at.desc())
        .all()
    )


def list_org_documents(
    session: Session, *, organization_id: str, q: str = "", limit: int = 100
) -> list[Document]:
    rows = (
        session.query(Document)
        .filter_by(organization_id=organization_id)
        .order_by(Document.created_at.desc())
        .limit(500)
        .all()
    )
    needle = (q or "").strip().casefold()
    if not needle:
        return rows[:limit]
    out = []
    for d in rows:
        blob = f"{d.title} {d.original_filename} {d.doc_kind}".casefold()
        if needle in blob:
            out.append(d)
    return out[:limit]


def absolute_path(doc: Document) -> Path:
    if not doc.party_id:
        raise ValueError("documento sin cliente")
    return party_dir(doc.organization_id, doc.party_id) / doc.stored_name


def delete_document(
    session: Session, *, organization_id: str, document_id: str, actor_id: str | None = None
) -> None:
    doc = session.get(Document, document_id)
    if doc is None or doc.organization_id != organization_id:
        raise ValueError("documento no encontrado")
    path = absolute_path(doc)
    session.delete(doc)
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="Document",
            entity_id=document_id,
            action="DELETED",
            detail_json=json.dumps({"filename": doc.original_filename}),
        )
    )
    session.flush()
    if path.exists():
        path.unlink()
