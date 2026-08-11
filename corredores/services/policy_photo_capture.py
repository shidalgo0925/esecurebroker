"""Capture policy data from photo/PDF — IA propone, humano confirma, dominio graba.

Never writes Domain Truth without explicit confirm. Optional OpenAI Vision when
OPENAI_API_KEY / settings.openai_api_key is configured.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from corredores.config import settings

DOC_MONTHS = {
    "ENE": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
    "DEC": 12,
}


@dataclass
class PolicyPhotoDraft:
    """Proposed fields from a policy photo — not Domain Truth until confirm."""

    # Cliente
    first_name: str = ""
    last_name: str = ""
    national_id: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    district: str = ""
    # Póliza
    carrier_name: str = ""
    policy_number: str = ""
    invoice_number: str = ""
    line_code: str = "AUTO"
    effective_date: str = ""  # ISO
    expiration_date: str = ""
    payment_form: str = ""
    annual_premium: str = ""
    num_payments: str = "1"
    # Vehículo
    make: str = ""
    model: str = ""
    year: str = ""
    plate: str = ""
    usage: str = ""
    vehicle_type: str = ""
    color: str = ""
    motor: str = ""
    chassis: str = ""
    # Meta
    broker_name: str = ""
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    source: str = "manual"  # manual|openai_vision|heuristic

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


EXTRACT_SCHEMA_HINT = """
Extrae JSON con exactamente estas claves (string vacío si no aparece):
first_name, last_name, national_id, phone, email, address, district,
carrier_name, policy_number, invoice_number, line_code,
effective_date (YYYY-MM-DD), expiration_date (YYYY-MM-DD),
payment_form, annual_premium, num_payments,
make, model, year, plate, usage, vehicle_type, color, motor, chassis,
broker_name, confidence (0-1).
Reglas:
- Póliza Panamá AUTO típica (FEDPA, SURA, ANCÓN, ASSA…).
- Cedula formato N-NNN-NNNN.
- Prima total a pagar → annual_premium (si es contado/1 cuota).
- CONTADO → num_payments=1; MENSUAL → inferir cuotas si hay calendario.
- No inventes montos ni fechas; si no se lee, deja "".
- line_code suele ser AUTO para Automóvil.
"""


def _parse_es_date(text: str) -> str:
    """26-DIC-25 / 26-DEC-2025 → ISO."""
    t = (text or "").strip().upper().replace(" ", "")
    m = re.match(r"^(\d{1,2})[-/]([A-Z]{3})[-/](\d{2,4})$", t)
    if not m:
        m2 = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", t)
        return t if m2 else ""
    day = int(m.group(1))
    mon = DOC_MONTHS.get(m.group(2), 0)
    year = int(m.group(3))
    if year < 100:
        year += 2000
    if not mon:
        return ""
    try:
        return date(year, mon, day).isoformat()
    except ValueError:
        return ""


def _split_person_name(full: str) -> tuple[str, str]:
    parts = [p for p in re.split(r"\s+", (full or "").strip()) if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0].title(), ""
    # Heurística Panamá: últimos 1–2 = apellidos
    if " DE " in f" {' '.join(parts)} ".upper() and len(parts) >= 3:
        return " ".join(parts[:-2]).title(), " ".join(parts[-2:]).title()
    return parts[0].title(), " ".join(parts[1:]).title()


def draft_from_mapping(data: dict[str, Any], *, source: str) -> PolicyPhotoDraft:
    d = PolicyPhotoDraft(source=source)
    for key in d.as_dict():
        if key in ("warnings", "source") or key not in data:
            continue
        val = data.get(key)
        if val is None:
            continue
        setattr(d, key, str(val).strip())
    if d.effective_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", d.effective_date):
        d.effective_date = _parse_es_date(d.effective_date)
    if d.expiration_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", d.expiration_date):
        d.expiration_date = _parse_es_date(d.expiration_date)
    try:
        d.confidence = float(data.get("confidence") or d.confidence or 0)
    except (TypeError, ValueError):
        d.confidence = 0.0
    if not d.line_code:
        d.line_code = "AUTO"
    return d


def extract_with_openai_vision(image_bytes: bytes, *, mime: str = "image/jpeg") -> PolicyPhotoDraft:
    api_key = (getattr(settings, "openai_api_key", None) or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY no configurada")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("paquete openai no instalado") from exc

    b64 = base64.b64encode(image_bytes).decode("ascii")
    client = OpenAI(api_key=api_key)
    model = getattr(settings, "openai_vision_model", None) or "gpt-4o-mini"
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "Eres un extractor de pólizas de seguros de Panamá. Solo JSON válido.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACT_SCHEMA_HINT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            },
        ],
    )
    raw = resp.choices[0].message.content or "{}"
    data = json.loads(raw)
    draft = draft_from_mapping(data, source="openai_vision")
    if draft.confidence <= 0:
        draft.confidence = 0.7
    return draft


def extract_heuristic_from_text(text: str) -> PolicyPhotoDraft:
    """Cheap regex pass when OCR/text is available (no inventa)."""
    d = PolicyPhotoDraft(source="heuristic", confidence=0.35)
    t = text or ""
    m = re.search(r"P[oó]liza\s*No\.?\s*[:#]?\s*([0-9\-]+)", t, re.I)
    if m:
        d.policy_number = m.group(1).strip()
    m = re.search(r"C[eé]dula\s*:?\s*([0-9\-]+)", t, re.I)
    if m:
        d.national_id = m.group(1).strip()
    m = re.search(r"(FEDPA|SURA|ANC[OÓ]N|ASSA|MAPFRE)", t, re.I)
    if m:
        d.carrier_name = m.group(1).upper().replace("Ó", "O")
        if d.carrier_name == "ANCON":
            d.carrier_name = "ANCÓN"
    m = re.search(r"Total a Pagar\s*:?\s*B?/?\.?\s*([0-9]+[.,][0-9]{2})", t, re.I)
    if m:
        d.annual_premium = m.group(1).replace(",", ".")
        d.num_payments = "1"
    m = re.search(r"Matr[ií]cula\s*:?\s*([A-Z0-9\-]+)", t, re.I)
    if m:
        d.plate = m.group(1).upper()
    m = re.search(r"\b(20\d{2})\b.*?(TOYOTA|MITSUBISHI|HYUNDAI|KIA|NISSAN|HONDA|FORD)", t, re.I)
    if m:
        d.year = m.group(1)
        d.make = m.group(2).upper()
    d.line_code = "AUTO"
    d.warnings.append("Extracción heurística — revisá todos los campos antes de guardar.")
    return d


def extract_policy_photo(
    image_bytes: bytes,
    *,
    filename: str = "",
    mime: str | None = None,
    ocr_text: str | None = None,
) -> PolicyPhotoDraft:
    """Try Vision API, else heuristic text, else empty draft for manual fill."""
    name = (filename or "").lower()
    mime = mime or ("image/png" if name.endswith(".png") else "image/jpeg")
    warnings: list[str] = []

    if getattr(settings, "openai_api_key", None):
        try:
            return extract_with_openai_vision(image_bytes, mime=mime)
        except Exception as exc:  # noqa: BLE001 — surface as warning, don't crash capture
            warnings.append(f"Visión IA no disponible ({exc}). Completá a mano.")

    if ocr_text and ocr_text.strip():
        draft = extract_heuristic_from_text(ocr_text)
        draft.warnings.extend(warnings)
        return draft

    draft = PolicyPhotoDraft(source="manual", confidence=0.0)
    draft.warnings.extend(warnings)
    draft.warnings.append(
        "Subí la foto: revisá/completá los datos. Con OPENAI_API_KEY la IA prellena desde la imagen."
    )
    draft.line_code = "AUTO"
    return draft


def premium_decimal(value: str) -> Decimal | None:
    try:
        v = Decimal(str(value).replace(",", "").strip())
        return v if v > 0 else None
    except (InvalidOperation, ValueError):
        return None
