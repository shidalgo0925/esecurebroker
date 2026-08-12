"""PDF text-layer capture without OpenAI."""

from pathlib import Path

from corredores.services.policy_photo_capture import extract_policy_photo

PDF = Path("/opt/corredores/var/uploads/era/polizar CAR QRT.pdf")


def test_extract_car_pdf_from_text_layer():
    if not PDF.is_file():
        return  # optional local fixture
    draft = extract_policy_photo(
        PDF.read_bytes(),
        filename=PDF.name,
        mime="application/pdf",
    )
    assert draft.source in {"pdf_text", "heuristic"}
    assert draft.line_code == "CAR"
    assert "ALIADO" in (draft.carrier_name or "").upper()
    assert draft.policy_number
    assert draft.annual_premium
    assert draft.effective_date.startswith("2026-07")
    assert draft.expiration_date.startswith("2027-07")
