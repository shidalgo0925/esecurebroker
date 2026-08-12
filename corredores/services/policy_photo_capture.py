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

from corredores.services.runtime_settings import runtime

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
    cfg = runtime()
    api_key = (cfg.get("capture.openai_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("OpenAI API key no configurada (Mantenimiento → Captura)")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("paquete openai no instalado") from exc

    b64 = base64.b64encode(image_bytes).decode("ascii")
    client = OpenAI(api_key=api_key)
    model = cfg.get("capture.openai_vision_model") or "gpt-4o-mini"
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


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Best-effort text layer extraction (no OCR). Empty if scanned-only."""
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        parts: list[str] = []
        for page in reader.pages[:8]:
            parts.append(page.extract_text() or "")
        return "\n".join(parts).strip()
    except Exception:  # noqa: BLE001
        return ""


def extract_heuristic_from_pdf_bytes(pdf_bytes: bytes) -> PolicyPhotoDraft:
    """Parse common Panamá policy PDF fields from text layer."""
    text = extract_text_from_pdf(pdf_bytes)
    if not text:
        d = PolicyPhotoDraft(source="manual", confidence=0.0)
        d.warnings.append("PDF sin texto extraíble (¿escaneado?). Completá a mano o configurá OPENAI_API_KEY.")
        return d
    d = extract_heuristic_from_text(text)
    # Aliado / ramos técnicos CAR
    if re.search(r"TODO\s+RIESGO\s+PARA\s+CONTRATISTA|RAMOS\s+TECNICOS", text, re.I):
        d.line_code = "CAR"
        d.warnings.append("Detectado Todo Riesgo Contratista (CAR).")
    if re.search(r"ALIADO\s+SEGUROS", text, re.I):
        d.carrier_name = "ALIADO"
    m = re.search(r"P[ÓO]LIZA\s*:\s*([0-9]+(?:\s+[0-9]+)*)", text, re.I)
    if m and not d.policy_number:
        d.policy_number = "-".join(p for p in m.group(1).split() if p)
    m = re.search(r"TOTAL\s+A\s+PAGAR\s*.*?([0-9]{1,3}(?:,[0-9]{3})*\.[0-9]{2}|[0-9]+\.[0-9]{2})", text, re.I | re.S)
    if m:
        d.annual_premium = m.group(1).replace(",", "")
    m = re.search(
        r"(\d{1,2}\s+de\s+[A-ZÁÉÍÓÚ]+(?:\s+de)?\s+\d{4})\s*DESDE:.*?(\d{1,2}\s+de\s+[A-ZÁÉÍÓÚ]+(?:\s+de)?\s+\d{4})\s*HASTA:",
        text,
        re.I | re.S,
    )
    # Dates often glued: "30 de JULIO de 2026DESDE:"
    m = re.search(r"(\d{1,2}\s+de\s+[A-ZÁÉÍÓÚ]+\s+de\s+\d{4})\s*DESDE:", text, re.I)
    if m:
        d.effective_date = _parse_long_es_date(m.group(1))
    m = re.search(r"(\d{1,2}\s+de\s+[A-ZÁÉÍÓÚ]+\s+de\s+\d{4})\s*HASTA:", text, re.I)
    if m:
        d.expiration_date = _parse_long_es_date(m.group(1))
    m = re.search(r"C[ÉE]DULA/RUC:\s*([0-9\-]+)", text, re.I)
    if m:
        d.national_id = m.group(1).strip()
    m = re.search(r"([A-Z0-9 .,&\-]+),\s*S\.A\.", text)
    if m and not d.first_name:
        # company → put legal name in last_name slot for review UI (party commit uses both)
        d.first_name = ""
        d.last_name = m.group(0).strip()
    if re.search(r"PAGO:\s*CONTADO", text, re.I):
        d.num_payments = "1"
        d.payment_form = "CONTADO"
    d.confidence = max(d.confidence, 0.55)
    d.source = "pdf_text"
    d.warnings.append("Extracción desde texto del PDF — revisá antes de confirmar.")
    return d


def _parse_long_es_date(text: str) -> str:
    """30 de JULIO de 2026 → ISO."""
    months = {
        "ENERO": 1,
        "FEBRERO": 2,
        "MARZO": 3,
        "ABRIL": 4,
        "MAYO": 5,
        "JUNIO": 6,
        "JULIO": 7,
        "AGOSTO": 8,
        "SEPTIEMBRE": 9,
        "OCTUBRE": 10,
        "NOVIEMBRE": 11,
        "DICIEMBRE": 12,
    }
    m = re.match(
        r"^\s*(\d{1,2})\s+de\s+([A-ZÁÉÍÓÚ]+)\s+de\s+(\d{4})\s*$",
        (text or "").strip(),
        re.I,
    )
    if not m:
        return ""
    day = int(m.group(1))
    mon = months.get(m.group(2).upper().replace("Á", "A").replace("É", "E"), 0)
    year = int(m.group(3))
    if not mon:
        # JULIO etc without accent issues
        mon = months.get(m.group(2).upper(), 0)
    if not mon:
        return ""
    try:
        return date(year, mon, day).isoformat()
    except ValueError:
        return ""


def extract_policy_photo(
    image_bytes: bytes,
    *,
    filename: str = "",
    mime: str | None = None,
    ocr_text: str | None = None,
) -> PolicyPhotoDraft:
    """Try Vision API, else PDF text / heuristic, else empty draft for manual fill."""
    name = (filename or "").lower()
    mime = mime or (
        "application/pdf"
        if name.endswith(".pdf")
        else ("image/png" if name.endswith(".png") else "image/jpeg")
    )
    warnings: list[str] = []

    has_openai = bool(runtime().get("capture.openai_api_key").strip())
    if has_openai and not (mime == "application/pdf" or name.endswith(".pdf")):
        try:
            return extract_with_openai_vision(image_bytes, mime=mime)
        except Exception as exc:  # noqa: BLE001 — surface as warning, don't crash capture
            warnings.append(f"Visión IA no disponible ({exc}). Completá a mano.")
    elif has_openai and (mime == "application/pdf" or name.endswith(".pdf")):
        # Vision on PDF: try API; if fails, fall through to text layer
        try:
            return extract_with_openai_vision(image_bytes, mime="application/pdf")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Visión IA PDF no disponible ({exc}). Probando texto del PDF.")

    if mime == "application/pdf" or name.endswith(".pdf") or image_bytes[:4] == b"%PDF":
        draft = extract_heuristic_from_pdf_bytes(image_bytes)
        draft.warnings = warnings + list(draft.warnings)
        return draft

    if ocr_text and ocr_text.strip():
        draft = extract_heuristic_from_text(ocr_text)
        draft.warnings.extend(warnings)
        return draft

    draft = PolicyPhotoDraft(source="manual", confidence=0.0)
    draft.warnings.extend(warnings)
    draft.warnings.append(
        "Subí la foto: revisá/completá los datos. Configurá OpenAI en Mantenimiento para prellenar desde imagen."
    )
    draft.line_code = "AUTO"
    return draft


def premium_decimal(value: str) -> Decimal | None:
    try:
        v = Decimal(str(value).replace(",", "").strip())
        return v if v > 0 else None
    except (InvalidOperation, ValueError):
        return None
