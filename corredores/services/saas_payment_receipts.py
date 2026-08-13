"""Comprobantes de pago SaaS (transferencia / Yappy) — pendiente de verificación."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from corredores.config import settings

MAX_RECEIPT_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic"}


def receipts_root() -> Path:
    base = Path(getattr(settings, "documents_root", "") or "/opt/corredores/var/documents")
    # Sibling of documents: …/var/saas_receipts
    root = base.parent / "saas_receipts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename(name: str) -> str:
    base = Path(name or "comprobante.bin").name
    base = re.sub(r"[^\w.\- ()áéíóúñÁÉÍÓÚÑ]+", "_", base, flags=re.UNICODE)
    return base[:200] or "comprobante.bin"


def _detect_ext(content: bytes, content_type: str | None, filename: str) -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    name = (filename or "").lower()
    if content.startswith(b"%PDF") or ctype == "application/pdf" or name.endswith(".pdf"):
        return ".pdf"
    if content.startswith(b"\xff\xd8\xff") or ctype in {"image/jpeg", "image/jpg"} or name.endswith(
        (".jpg", ".jpeg")
    ):
        return ".jpg"
    if content.startswith(b"\x89PNG") or ctype == "image/png" or name.endswith(".png"):
        return ".png"
    if (content[:4] == b"RIFF" and b"WEBP" in content[:16]) or ctype == "image/webp" or name.endswith(
        ".webp"
    ):
        return ".webp"
    if name.endswith(".heic") or ctype == "image/heic":
        return ".heic"
    # Accept any non-empty upload for now (verification is manual / future IA).
    suf = Path(name).suffix.lower()
    if suf in ALLOWED_EXTS:
        return suf
    return ".bin"


def save_saas_payment_receipt(
    *,
    organization_id: str,
    method: str,
    filename: str,
    content: bytes,
    content_type: str | None = None,
) -> dict:
    """Persist receipt bytes. Returns metadata for audit (no content validation beyond size/empty)."""
    if not content:
        raise ValueError("Debes subir el comprobante de pago.")
    if len(content) > MAX_RECEIPT_BYTES:
        raise ValueError("El comprobante no puede superar 10 MB.")

    ext = _detect_ext(content, content_type, filename)
    original = _safe_filename(filename)
    if not Path(original).suffix:
        original = f"{original}{ext}"
    stored = f"{uuid.uuid4().hex}{ext}"
    dest_dir = receipts_root() / organization_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / stored
    dest.write_bytes(content)

    return {
        "stored_name": stored,
        "original_filename": original,
        "relative_path": f"{organization_id}/{stored}",
        "absolute_path": str(dest),
        "size_bytes": len(content),
        "content_type": (content_type or "").split(";")[0].strip().lower() or None,
        "method": method,
        "verification_status": "pending",
    }
