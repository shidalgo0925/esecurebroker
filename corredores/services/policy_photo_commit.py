"""Commit a reviewed/auto PolicyPhotoDraft into Domain Truth."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from corredores.domain.enums import DataSource, DueDateSource, PolicyStatus, TermSource
from corredores.domain.models import (
    Carrier,
    Installment,
    InsuranceLine,
    Party,
    PaymentPlan,
    Policy,
    PolicyTerm,
    VehicleRisk,
)
from corredores.services.auto_e2e import ensure_auto_line, generate_proposed_installments, suggest_policy_term
from corredores.services.documents import save_party_pdf
from corredores.services.materialize_portfolio import materialize_portfolio
from corredores.services.policy_photo_capture import PolicyPhotoDraft, premium_decimal

ONE_CLICK_MIN_CONFIDENCE = 0.85


def draft_ready_for_one_click(draft: PolicyPhotoDraft) -> tuple[bool, list[str]]:
    missing: list[str] = []
    if not (draft.policy_number or "").strip():
        missing.append("nº póliza")
    if not (draft.national_id or "").strip() and not (
        (draft.first_name or "").strip() or (draft.last_name or "").strip()
    ):
        missing.append("cliente (cédula o nombre)")
    if not (draft.carrier_name or "").strip():
        missing.append("compañía")
    if not (draft.effective_date or "").strip():
        missing.append("vigencia inicio")
    if not premium_decimal(draft.annual_premium):
        missing.append("prima / total")
    if draft.confidence < ONE_CLICK_MIN_CONFIDENCE:
        missing.append(f"confianza IA ({draft.confidence:.0%} < {ONE_CLICK_MIN_CONFIDENCE:.0%})")
    return (len(missing) == 0, missing)


def resolve_carrier_id(session: Session, organization_id: str, carrier_name: str) -> str | None:
    name = (carrier_name or "").strip().upper()
    if not name:
        return None
    rows = session.query(Carrier).filter_by(organization_id=organization_id).all()
    for c in rows:
        cn = (c.name or "").upper()
        code = (c.code or "").upper()
        if name == cn or name == code or name in cn or cn in name:
            return c.id
    # soft aliases
    aliases = {
        "FEDPA": "FEDPA",
        "SURA": "SURA",
        "ANCON": "ANCON",
        "ANCÓN": "ANCON",
        "ASSA": "ASSA",
        "MAPFRE": "MAPFRE",
    }
    key = aliases.get(name)
    if key:
        for c in rows:
            if key in (c.code or "").upper() or key in (c.name or "").upper():
                return c.id
    return None


def commit_policy_from_draft(
    session: Session,
    *,
    organization_id: str,
    draft: PolicyPhotoDraft,
    actor_id: str | None,
    carrier_id: str | None = None,
    line_id: str | None = None,
    attach_bytes: bytes | None = None,
    attach_filename: str | None = None,
    attach_mime: str | None = None,
) -> Policy:
    carrier_id = carrier_id or resolve_carrier_id(session, organization_id, draft.carrier_name)
    if not carrier_id:
        raise ValueError("no se pudo resolver la aseguradora — elegila en revisión")
    if not (draft.policy_number or "").strip():
        raise ValueError("falta número de póliza")

    nid = (draft.national_id or "").strip() or None
    party = None
    if nid:
        party = (
            session.query(Party)
            .filter_by(organization_id=organization_id, national_id=nid)
            .one_or_none()
        )
    if party is None:
        party = Party(
            organization_id=organization_id,
            party_type="PERSON",
            first_name=(draft.first_name or "").strip() or None,
            last_name=(draft.last_name or "").strip() or None,
            national_id=nid,
            phone=(draft.phone or "").strip() or None,
            email=(draft.email or "").strip() or None,
            district=(draft.district or "").strip() or None,
            address=(draft.address or "").strip() or None,
            data_source=DataSource.MANUAL,
        )
        session.add(party)
        session.flush()
    else:
        party.first_name = (draft.first_name or "").strip() or party.first_name
        party.last_name = (draft.last_name or "").strip() or party.last_name
        party.phone = (draft.phone or "").strip() or party.phone
        party.email = (draft.email or "").strip() or party.email
        party.district = (draft.district or "").strip() or party.district
        party.address = (draft.address or "").strip() or party.address

    line = session.get(InsuranceLine, line_id) if line_id else None
    if line is None:
        code = (draft.line_code or "AUTO").strip().upper() or "AUTO"
        line = session.query(InsuranceLine).filter_by(code=code).one_or_none() or ensure_auto_line(session)

    eff = date.fromisoformat(draft.effective_date) if draft.effective_date else date.today()
    exp_in = date.fromisoformat(draft.expiration_date) if draft.expiration_date else None
    eff, exp, term_src = suggest_policy_term(
        eff, expiration_date=exp_in, term_source=TermSource.MANUAL if exp_in else TermSource.SYSTEM_GENERATED
    )
    premium = premium_decimal(draft.annual_premium) or Decimal("0")
    try:
        n_pay = max(1, int(str(draft.num_payments or "1").strip() or "1"))
    except ValueError:
        n_pay = 1

    existing = (
        session.query(Policy)
        .filter_by(
            organization_id=organization_id,
            carrier_id=carrier_id,
            insurance_line_id=line.id,
            policy_number=draft.policy_number.strip(),
        )
        .first()
    )
    if existing is not None:
        return existing

    notes = []
    if draft.invoice_number:
        notes.append(f"factura:{draft.invoice_number}")
    if draft.payment_form:
        notes.append(f"forma_pago:{draft.payment_form}")
    if draft.color:
        notes.append(f"color:{draft.color}")
    if draft.motor:
        notes.append(f"motor:{draft.motor}")
    if draft.chassis:
        notes.append(f"chasis:{draft.chassis}")

    policy = Policy(
        organization_id=organization_id,
        carrier_id=carrier_id,
        insurance_line_id=line.id,
        policy_number=draft.policy_number.strip(),
        status=PolicyStatus.ACTIVE,
        client_party_id=party.id,
        annual_premium=premium if premium > 0 else None,
        net_premium=premium if premium > 0 else None,
        data_source=DataSource.MANUAL,
    )
    session.add(policy)
    session.flush()
    session.add(
        PolicyTerm(policy_id=policy.id, effective_date=eff, expiration_date=exp, term_source=term_src)
    )
    if line.code == "AUTO":
        year_val = None
        if (draft.year or "").strip().isdigit():
            year_val = int(draft.year.strip())
        usage = re.sub(r"\s+", " ", (draft.usage or "").strip().upper()) or None
        session.add(
            VehicleRisk(
                organization_id=organization_id,
                policy_id=policy.id,
                make=(draft.make or "").strip() or None,
                model=(draft.model or "").strip() or None,
                plate=(draft.plate or "").strip() or None,
                year=year_val,
                vehicle_type=(draft.vehicle_type or "").strip() or None,
                usage=usage,
            )
        )
    if premium > 0 and n_pay >= 1:
        plan = PaymentPlan(
            policy_id=policy.id,
            confirmed=True,
            notes="captura foto" + ((" · " + " · ".join(notes)) if notes else ""),
        )
        session.add(plan)
        session.flush()
        for num, due, amt in generate_proposed_installments(
            start_due=eff, count=n_pay, total_amount=premium
        ):
            session.add(
                Installment(
                    payment_plan_id=plan.id,
                    installment_number=num,
                    due_date=due,
                    amount=amt,
                    due_date_source=DueDateSource.SYSTEM_GENERATED,
                )
            )

    if attach_bytes:
        save_party_pdf(
            session,
            organization_id=organization_id,
            party_id=party.id,
            filename=attach_filename or "poliza.jpg",
            content=attach_bytes,
            content_type=attach_mime,
            title=f"Póliza {draft.policy_number.strip()}",
            doc_kind="POLIZA",
            policy_id=policy.id,
            actor_id=actor_id,
        )

    materialize_portfolio(session, organization_id=organization_id, actor_id=actor_id or "photo-capture")
    return policy
