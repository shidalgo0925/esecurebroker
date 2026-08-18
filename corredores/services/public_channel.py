"""Public sales channel — anonymous quote/checkout services (F1).

Pricing reads PublicPlanRate rows (DEV_PLACEHOLDER until real tariffs).
Never trusts browser price or organization_id.
"""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session

from corredores.domain.crm_constants import (
    PROSPECT_OPEN,
    PROSPECT_PERSON,
    STAGE_QUOTING,
)
from corredores.domain.models import (
    CrmLeadSource,
    CrmOpportunity,
    CrmPipelineStage,
    CrmProspect,
    Organization,
    Policy,
    PublicPlanRate,
    PublicProductPlan,
    PublicQuote,
    PublicQuoteBeneficiary,
    PublicQuoteEmergencyContact,
    PublicQuoteTraveler,
    PublicSalesChannel,
)
from corredores.domain.public_channel_constants import (
    DESTINATION_REGIONS,
    PAYMENT_NONE,
    PAYMENT_PENDING,
    QUOTE_CHECKOUT_PENDING,
    QUOTE_CUSTOMER_DATA,
    QUOTE_PAID,
    QUOTE_PLAN_SELECTED,
    QUOTE_QUOTED,
    QUOTE_STARTED,
    REGION_CODES,
)
from corredores.services.crm_catalog_seed import ensure_default_crm_catalogs


class PublicChannelError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _loads(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def trip_days(start: date, end: date) -> int:
    """Days from start to end (end - start). Same calendar day → 1."""
    if end < start:
        raise PublicChannelError("fecha fin debe ser ≥ fecha inicio")
    return max((end - start).days, 1)


def get_channel_by_slug(session: Session, slug: str) -> PublicSalesChannel:
    ch = (
        session.query(PublicSalesChannel)
        .filter_by(slug=slug.strip().lower(), active=True)
        .one_or_none()
    )
    if ch is None:
        raise PublicChannelError("canal no encontrado")
    org = session.get(Organization, ch.organization_id)
    if org is None or not org.active:
        raise PublicChannelError("organización inactiva")
    return ch


def get_quote_by_token(
    session: Session, *, channel: PublicSalesChannel, token: str
) -> PublicQuote:
    q = (
        session.query(PublicQuote)
        .filter_by(channel_id=channel.id, public_token=token)
        .one_or_none()
    )
    if q is None:
        raise PublicChannelError("cotización no encontrada")
    if q.organization_id != channel.organization_id:
        raise PublicChannelError("cotización no encontrada")
    if q.expires_at and q.expires_at < _now() and q.status not in (
        "PAID",
        "COMPLETED",
    ):
        q.status = "EXPIRED"
        session.flush()
        raise PublicChannelError("cotización expirada")
    return q


def channel_config_dict(session: Session, channel: PublicSalesChannel) -> dict[str, Any]:
    branding = _loads(channel.branding_json, {}) or {}
    plans = (
        session.query(PublicProductPlan)
        .filter_by(channel_id=channel.id, active=True)
        .order_by(PublicProductPlan.sort_order, PublicProductPlan.name)
        .all()
    )
    return {
        "slug": channel.slug,
        "name": channel.name,
        "product_code": channel.product_code,
        "product_label": channel.product_label,
        "origin_default": channel.origin_default,
        "origin_fixed": channel.origin_fixed,
        "currency": channel.currency,
        "destinations": [{"code": c, "label": lab} for c, lab in DESTINATION_REGIONS],
        "branding": branding,
        "plans_preview": [
            {
                "code": p.code,
                "name": p.name,
                "highlight": p.highlight,
                "coverages": _loads(p.coverages_json, []),
                "limits": _loads(p.limits_json, {}),
            }
            for p in plans
        ],
        "rates_note": "DEV_PLACEHOLDER — tarifas de catálogo provisional, no oficiales",
    }


def create_quote(session: Session, channel: PublicSalesChannel) -> PublicQuote:
    token = secrets.token_urlsafe(32)
    q = PublicQuote(
        public_token=token,
        channel_id=channel.id,
        organization_id=channel.organization_id,
        status=QUOTE_STARTED,
        origin=channel.origin_default,
        passenger_count=1,
        currency=channel.currency,
        payment_status=PAYMENT_NONE,
        expires_at=_now() + timedelta(days=7),
    )
    session.add(q)
    session.flush()
    return q


def update_trip(
    session: Session,
    quote: PublicQuote,
    *,
    origin: str | None,
    destination_region: str,
    destination: str | None,
    start_date: date,
    end_date: date,
    ages: list[int],
) -> PublicQuote:
    if quote.status not in (QUOTE_STARTED, QUOTE_QUOTED, QUOTE_PLAN_SELECTED):
        raise PublicChannelError("no se puede modificar el viaje en este estado")
    region = destination_region.upper().strip()
    if region not in REGION_CODES:
        raise PublicChannelError("destino inválido")
    if not ages:
        raise PublicChannelError("indique al menos un pasajero (edad)")
    for a in ages:
        if a < 0 or a > 120:
            raise PublicChannelError("edad inválida")
    days = trip_days(start_date, end_date)
    ch = session.get(PublicSalesChannel, quote.channel_id)
    assert ch is not None
    if ch.origin_fixed:
        quote.origin = ch.origin_default
    else:
        quote.origin = (origin or ch.origin_default or "").strip() or ch.origin_default
    quote.destination_region = region
    quote.destination = (destination or dict(DESTINATION_REGIONS).get(region, region)).strip()
    quote.start_date = start_date
    quote.end_date = end_date
    quote.days = days
    quote.passenger_count = len(ages)
    quote.ages_json = _dumps(ages)
    # Changing trip invalidates selection
    quote.selected_plan_code = None
    quote.selected_plan_snapshot_json = None
    quote.selected_premium = None
    quote.selected_at = None
    quote.status = QUOTE_STARTED
    quote.quoted_plans_json = None
    session.flush()
    return quote


def _rate_for(
    session: Session, plan_id: str, region: str, age: int
) -> PublicPlanRate | None:
    rows = (
        session.query(PublicPlanRate)
        .filter_by(plan_id=plan_id, destination_region=region, active=True)
        .all()
    )
    for r in rows:
        if r.age_min <= age <= r.age_max:
            return r
    return None


def calculate_plans(session: Session, quote: PublicQuote) -> list[dict[str, Any]]:
    if not quote.start_date or not quote.end_date or not quote.destination_region:
        raise PublicChannelError("complete los datos del viaje primero")
    ages = _loads(quote.ages_json, []) or []
    if not ages:
        raise PublicChannelError("edades requeridas")
    days = quote.days or trip_days(quote.start_date, quote.end_date)
    plans = (
        session.query(PublicProductPlan)
        .filter_by(channel_id=quote.channel_id, active=True)
        .order_by(PublicProductPlan.sort_order)
        .all()
    )
    if not plans:
        raise PublicChannelError("no hay planes configurados para este canal")
    out: list[dict[str, Any]] = []
    for plan in plans:
        total = Decimal("0")
        breakdown: list[dict[str, Any]] = []
        ok = True
        for idx, age in enumerate(ages):
            rate = _rate_for(session, plan.id, quote.destination_region, int(age))
            if rate is None:
                ok = False
                break
            line = _money(Decimal(rate.amount_per_passenger_per_day) * Decimal(days))
            total += line
            breakdown.append(
                {
                    "passenger": idx + 1,
                    "age": int(age),
                    "per_day": str(rate.amount_per_passenger_per_day),
                    "days": days,
                    "subtotal": str(line),
                    "rate_note": rate.notes,
                }
            )
        if not ok:
            continue
        total = _money(total)
        out.append(
            {
                "code": plan.code,
                "name": plan.name,
                "currency": plan.currency or quote.currency,
                "premium": str(total),
                "highlight": plan.highlight,
                "coverages": _loads(plan.coverages_json, []),
                "limits": _loads(plan.limits_json, {}),
                "breakdown": breakdown,
                "pricing_source": "public_plan_rates",
                "pricing_note": "DEV_PLACEHOLDER",
            }
        )
    if not out:
        raise PublicChannelError("sin tarifas para este destino/edades")
    quote.quoted_plans_json = _dumps(out)
    quote.quoted_at = _now()
    quote.status = QUOTE_QUOTED
    quote.selected_plan_code = None
    quote.selected_plan_snapshot_json = None
    quote.selected_premium = None
    session.flush()
    return out


def select_plan(session: Session, quote: PublicQuote, plan_code: str) -> PublicQuote:
    plans = _loads(quote.quoted_plans_json, []) or []
    if not plans:
        raise PublicChannelError("calcule la cotización antes de seleccionar")
    code = plan_code.strip().upper()
    match = next((p for p in plans if str(p.get("code", "")).upper() == code), None)
    if match is None:
        raise PublicChannelError("plan no válido para esta cotización")
    # Freeze snapshot — ignore any client-sent price
    snap = dict(match)
    snap["frozen_at"] = _now().isoformat()
    quote.selected_plan_code = match["code"]
    quote.selected_plan_snapshot_json = _dumps(snap)
    quote.selected_premium = Decimal(str(match["premium"]))
    quote.currency = match.get("currency") or quote.currency
    quote.selected_at = _now()
    quote.status = QUOTE_PLAN_SELECTED
    session.flush()
    return quote


def _ensure_crm(session: Session, quote: PublicQuote, primary: PublicQuoteTraveler) -> None:
    ensure_default_crm_catalogs(session, quote.organization_id)
    ch = session.get(PublicSalesChannel, quote.channel_id)
    assert ch is not None
    source_id = ch.lead_source_id
    if not source_id:
        web = (
            session.query(CrmLeadSource)
            .filter_by(organization_id=quote.organization_id, code="WEB", active=True)
            .one_or_none()
        )
        source_id = web.id if web else None

    actor = f"public_channel:{ch.slug}"
    if quote.crm_prospect_id:
        prosp = session.get(CrmProspect, quote.crm_prospect_id)
        if prosp and prosp.organization_id == quote.organization_id:
            prosp.first_name = primary.first_name
            prosp.last_name = primary.last_name
            prosp.email = primary.email
            prosp.phone = primary.phone
            prosp.mobile = primary.phone
            prosp.identification_number = primary.identification_number
            session.flush()
            return

    prosp = CrmProspect(
        organization_id=quote.organization_id,
        prospect_type=PROSPECT_PERSON,
        first_name=primary.first_name,
        last_name=primary.last_name,
        email=(primary.email or "").lower() or None,
        phone=primary.phone,
        mobile=primary.phone,
        identification_number=primary.identification_number,
        source_id=source_id,
        assigned_producer_id=ch.default_producer_profile_id,
        status=PROSPECT_OPEN,
        notes=f"Canal público {ch.slug} · quote {quote.public_token[:8]}…",
        created_by=actor,
    )
    session.add(prosp)
    session.flush()
    quote.crm_prospect_id = prosp.id

    stage = (
        session.query(CrmPipelineStage)
        .filter_by(organization_id=quote.organization_id, code=STAGE_QUOTING, active=True)
        .one_or_none()
    )
    title = f"Viaje {quote.origin or ''} → {quote.destination or quote.destination_region}"
    opp = CrmOpportunity(
        organization_id=quote.organization_id,
        prospect_id=prosp.id,
        title=title.strip()[:200] or "Cotización viaje (canal público)",
        product_interest=ch.product_label,
        assigned_producer_id=ch.default_producer_profile_id,
        stage_id=stage.id if stage else None,
        stage_code=STAGE_QUOTING,
        estimated_premium=quote.selected_premium,
        source_id=source_id,
        notes=f"public_quote_token={quote.public_token}",
        created_by=actor,
    )
    session.add(opp)
    session.flush()
    quote.crm_opportunity_id = opp.id


def save_travelers(
    session: Session, quote: PublicQuote, travelers: list[dict[str, Any]]
) -> list[PublicQuoteTraveler]:
    if quote.status not in (QUOTE_PLAN_SELECTED, QUOTE_CUSTOMER_DATA, QUOTE_CHECKOUT_PENDING):
        raise PublicChannelError("seleccione un plan antes de capturar pasajeros")
    if len(travelers) != quote.passenger_count:
        raise PublicChannelError(
            f"se esperan {quote.passenger_count} pasajeros"
        )
    ages = _loads(quote.ages_json, []) or []
    session.query(PublicQuoteBeneficiary).filter(
        PublicQuoteBeneficiary.traveler_id.in_(
            session.query(PublicQuoteTraveler.id).filter_by(quote_id=quote.id)
        )
    ).delete(synchronize_session=False)
    session.query(PublicQuoteTraveler).filter_by(quote_id=quote.id).delete()
    session.flush()

    rows: list[PublicQuoteTraveler] = []
    for i, t in enumerate(travelers):
        fn = (t.get("first_name") or "").strip()
        ln = (t.get("last_name") or "").strip()
        if not fn or not ln:
            raise PublicChannelError(f"pasajero {i + 1}: nombres y apellidos requeridos")
        bd_raw = t.get("birth_date")
        birth: date | None = None
        if bd_raw:
            birth = date.fromisoformat(str(bd_raw)[:10])
        age = t.get("age")
        if age is None and i < len(ages):
            age = ages[i]
        if age is None:
            raise PublicChannelError(f"pasajero {i + 1}: edad requerida")
        age = int(age)
        if birth and ages and i < len(ages):
            # Soft coherence check — block only large mismatches
            if abs(age - int(ages[i])) > 1:
                raise PublicChannelError(
                    f"pasajero {i + 1}: edad no coincide con la cotizada ({ages[i]})"
                )
        email = (t.get("email") or "").strip() or None
        phone = (t.get("phone") or "").strip() or None
        is_primary = bool(t.get("is_primary")) or i == 0
        if is_primary and not (email or phone):
            raise PublicChannelError("titular: correo o teléfono requerido")
        row = PublicQuoteTraveler(
            quote_id=quote.id,
            seq=i + 1,
            first_name=fn,
            last_name=ln,
            birth_date=birth,
            age=age,
            identification_number=(t.get("identification_number") or "").strip() or None,
            email=email.lower() if email else None,
            phone=phone,
            is_pep=bool(t.get("is_pep")),
            is_primary=is_primary,
        )
        session.add(row)
        rows.append(row)
    session.flush()
    primary = next((r for r in rows if r.is_primary), rows[0])
    _ensure_crm(session, quote, primary)
    quote.status = QUOTE_CUSTOMER_DATA
    session.flush()
    return rows


def save_beneficiaries(
    session: Session,
    quote: PublicQuote,
    by_traveler: list[dict[str, Any]],
) -> None:
    """by_traveler: [{traveler_seq, beneficiaries: [{full_name, relationship, ...}]}]"""
    if quote.status not in (QUOTE_CUSTOMER_DATA, QUOTE_CHECKOUT_PENDING, QUOTE_PLAN_SELECTED):
        raise PublicChannelError("complete pasajeros antes de beneficiarios")
    travelers = (
        session.query(PublicQuoteTraveler)
        .filter_by(quote_id=quote.id)
        .order_by(PublicQuoteTraveler.seq)
        .all()
    )
    by_seq = {t.seq: t for t in travelers}
    for block in by_traveler:
        seq = int(block.get("traveler_seq") or 0)
        tr = by_seq.get(seq)
        if tr is None:
            raise PublicChannelError(f"pasajero seq={seq} no encontrado")
        session.query(PublicQuoteBeneficiary).filter_by(traveler_id=tr.id).delete()
        bens = block.get("beneficiaries") or []
        for j, b in enumerate(bens):
            name = (b.get("full_name") or "").strip()
            if not name:
                continue
            session.add(
                PublicQuoteBeneficiary(
                    traveler_id=tr.id,
                    seq=j + 1,
                    full_name=name,
                    relationship=(b.get("relationship") or "").strip() or None,
                    identification_number=(b.get("identification_number") or "").strip()
                    or None,
                    phone=(b.get("phone") or "").strip() or None,
                    share_pct=(
                        Decimal(str(b["share_pct"])) if b.get("share_pct") is not None else None
                    ),
                )
            )
    session.flush()


def save_emergency(
    session: Session,
    quote: PublicQuote,
    *,
    name: str,
    phone: str,
    email: str | None,
) -> PublicQuoteEmergencyContact:
    name = name.strip()
    phone = phone.strip()
    if not name or not phone:
        raise PublicChannelError("contacto de emergencia: nombre y teléfono requeridos")
    existing = (
        session.query(PublicQuoteEmergencyContact).filter_by(quote_id=quote.id).one_or_none()
    )
    if existing:
        existing.name = name
        existing.phone = phone
        existing.email = (email or "").strip() or None
        session.flush()
        return existing
    row = PublicQuoteEmergencyContact(
        quote_id=quote.id,
        name=name,
        phone=phone,
        email=(email or "").strip() or None,
    )
    session.add(row)
    session.flush()
    return row


def quote_dict(session: Session, quote: PublicQuote) -> dict[str, Any]:
    travelers = (
        session.query(PublicQuoteTraveler)
        .filter_by(quote_id=quote.id)
        .order_by(PublicQuoteTraveler.seq)
        .all()
    )
    emergency = (
        session.query(PublicQuoteEmergencyContact).filter_by(quote_id=quote.id).one_or_none()
    )
    policy_number = None
    if quote.policy_id:
        pol = session.get(Policy, quote.policy_id)
        if pol:
            policy_number = pol.policy_number
    bens_out: list[dict[str, Any]] = []
    for tr in travelers:
        bens = (
            session.query(PublicQuoteBeneficiary)
            .filter_by(traveler_id=tr.id)
            .order_by(PublicQuoteBeneficiary.seq)
            .all()
        )
        bens_out.append(
            {
                "traveler_seq": tr.seq,
                "beneficiaries": [
                    {
                        "seq": b.seq,
                        "full_name": b.full_name,
                        "relationship": b.relationship,
                        "identification_number": b.identification_number,
                        "phone": b.phone,
                        "share_pct": str(b.share_pct) if b.share_pct is not None else None,
                    }
                    for b in bens
                ],
            }
        )
    return {
        "token": quote.public_token,
        "status": quote.status,
        "origin": quote.origin,
        "destination": quote.destination,
        "destination_region": quote.destination_region,
        "start_date": quote.start_date.isoformat() if quote.start_date else None,
        "end_date": quote.end_date.isoformat() if quote.end_date else None,
        "days": quote.days,
        "passenger_count": quote.passenger_count,
        "ages": _loads(quote.ages_json, []),
        "plans": _loads(quote.quoted_plans_json, []),
        "selected_plan_code": quote.selected_plan_code,
        "selected_plan": _loads(quote.selected_plan_snapshot_json),
        "currency": quote.currency,
        "selected_premium": str(quote.selected_premium) if quote.selected_premium else None,
        "payment_status": quote.payment_status,
        "checkout_ref": quote.checkout_ref,
        "party_id": quote.party_id,
        "policy_id": quote.policy_id,
        "policy_number": policy_number,
        "travelers": [
            {
                "seq": t.seq,
                "first_name": t.first_name,
                "last_name": t.last_name,
                "birth_date": t.birth_date.isoformat() if t.birth_date else None,
                "age": t.age,
                "identification_number": t.identification_number,
                "email": t.email,
                "phone": t.phone,
                "is_pep": t.is_pep,
                "is_primary": t.is_primary,
            }
            for t in travelers
        ],
        "beneficiaries": bens_out,
        "emergency_contact": (
            {
                "name": emergency.name,
                "phone": emergency.phone,
                "email": emergency.email,
            }
            if emergency
            else None
        ),
    }


def start_checkout(session: Session, quote: PublicQuote) -> dict[str, Any]:
    """Create payment attempt and return provider redirect (Stripe or DEV sandbox)."""
    if quote.status not in (QUOTE_CUSTOMER_DATA, QUOTE_CHECKOUT_PENDING, QUOTE_PAID):
        raise PublicChannelError("complete los datos antes del pago")
    if not quote.selected_premium or not quote.selected_plan_snapshot_json:
        raise PublicChannelError("plan no seleccionado")
    travelers = session.query(PublicQuoteTraveler).filter_by(quote_id=quote.id).count()
    if travelers != quote.passenger_count:
        raise PublicChannelError("pasajeros incompletos")
    emergency = (
        session.query(PublicQuoteEmergencyContact).filter_by(quote_id=quote.id).one_or_none()
    )
    if emergency is None:
        raise PublicChannelError("contacto de emergencia requerido")
    snap = _loads(quote.selected_plan_snapshot_json) or {}
    server_premium = Decimal(str(snap.get("premium", quote.selected_premium)))
    if _money(server_premium) != _money(Decimal(quote.selected_premium)):
        raise PublicChannelError("precio inconsistente — recotice")
    channel = session.get(PublicSalesChannel, quote.channel_id)
    if channel is None:
        raise PublicChannelError("canal no encontrado")
    from corredores.services.public_channel_payments import start_payment_checkout

    return start_payment_checkout(session, quote, channel)
