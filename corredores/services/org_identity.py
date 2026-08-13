"""Identidad de la correduría — datos + logo para documentos PDF/print."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from corredores.domain.models import Organization
from corredores.services.documents import documents_root

MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB
_ALLOWED_LOGO = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


@dataclass
class OrgIdentity:
    organization_id: str
    name: str
    legal_name: str | None
    trade_name: str | None
    tax_id: str | None
    phone: str | None
    email: str | None
    website: str | None
    address: str | None
    slogan: str | None
    document_footer: str | None
    logo_relpath: str | None
    has_logo: bool

    @property
    def display_name(self) -> str:
        return (self.trade_name or self.name or self.legal_name or "Correduría").strip()


def get_identity(session: Session, organization_id: str) -> OrgIdentity | None:
    org = session.get(Organization, organization_id)
    if org is None:
        return None
    return OrgIdentity(
        organization_id=org.id,
        name=org.name,
        legal_name=org.legal_name,
        trade_name=org.trade_name,
        tax_id=org.tax_id,
        phone=org.phone,
        email=org.email,
        website=org.website,
        address=org.address,
        slogan=org.slogan,
        document_footer=org.document_footer,
        logo_relpath=org.logo_relpath,
        has_logo=bool(org.logo_relpath),
    )


def update_identity(
    session: Session,
    organization_id: str,
    *,
    name: str,
    legal_name: str | None = None,
    trade_name: str | None = None,
    tax_id: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    website: str | None = None,
    address: str | None = None,
    slogan: str | None = None,
    document_footer: str | None = None,
) -> Organization:
    org = session.get(Organization, organization_id)
    if org is None:
        raise ValueError("organización no encontrada")
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("el nombre comercial es obligatorio")
    org.name = cleaned[:200]
    org.legal_name = (legal_name or "").strip()[:200] or None
    org.trade_name = (trade_name or "").strip()[:200] or None
    org.tax_id = (tax_id or "").strip()[:64] or None
    org.phone = (phone or "").strip()[:40] or None
    org.email = (email or "").strip()[:200] or None
    org.website = (website or "").strip()[:200] or None
    org.address = (address or "").strip() or None
    org.slogan = (slogan or "").strip()[:240] or None
    org.document_footer = (document_footer or "").strip()[:500] or None
    session.flush()
    return org


def _brand_dir(organization_id: str) -> Path:
    path = documents_root() / organization_id / "brand"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _detect_logo_ext(content: bytes, filename: str) -> str:
    name = (filename or "").lower()
    if content.startswith(b"\x89PNG") or name.endswith(".png"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff") or name.endswith((".jpg", ".jpeg")):
        return ".jpg"
    if (content[:4] == b"RIFF" and b"WEBP" in content[:16]) or name.endswith(".webp"):
        return ".webp"
    if content.lstrip().startswith(b"<svg") or name.endswith(".svg"):
        # basic SVG sniff
        head = content[:200].lower()
        if b"<svg" in head:
            return ".svg"
    raise ValueError("logo: use PNG, JPG, WEBP o SVG")


def save_logo(
    session: Session,
    organization_id: str,
    *,
    filename: str,
    content: bytes,
) -> Organization:
    org = session.get(Organization, organization_id)
    if org is None:
        raise ValueError("organización no encontrada")
    if not content:
        raise ValueError("archivo vacío")
    if len(content) > MAX_LOGO_BYTES:
        raise ValueError("logo demasiado grande (máx. 2 MB)")
    ext = _detect_logo_ext(content, filename)
    if ext not in _ALLOWED_LOGO:
        raise ValueError("formato de logo no permitido")
    brand = _brand_dir(organization_id)
    # Limpia logos previos del tenant
    for old in brand.glob("logo.*"):
        try:
            old.unlink()
        except OSError:
            pass
    safe = re.sub(r"[^\w.\-]+", "_", Path(filename).stem)[:40] or "logo"
    stored = brand / f"logo{ext}"
    stored.write_bytes(content)
    org.logo_relpath = f"{organization_id}/brand/{stored.name}"
    session.flush()
    return org


def clear_logo(session: Session, organization_id: str) -> Organization:
    org = session.get(Organization, organization_id)
    if org is None:
        raise ValueError("organización no encontrada")
    if org.logo_relpath:
        path = documents_root() / org.logo_relpath
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
    org.logo_relpath = None
    session.flush()
    return org


def logo_absolute_path(org: Organization | OrgIdentity) -> Path | None:
    rel = getattr(org, "logo_relpath", None)
    if not rel:
        return None
    path = documents_root() / rel
    return path if path.is_file() else None
