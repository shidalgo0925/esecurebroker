"""After public-channel PAID: materialize ESB Party + Policy (Grupo Arsi cartera).

Landing is commercial UI only. ESB remains system of record.
Does NOT create domain Payment / PaymentAllocation (cobranza UI / operador).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from corredores.domain.crm_constants import PROSPECT_CONVERTED
from corredores.domain.enums import (
    DataSource,
    DueDateSource,
    PartyRoleType,
    PartyType,
    PolicyStatus,
    TermSource,
)
from corredores.domain.models import (
    AuditEvent,
    Carrier,
    CrmOpportunity,
    CrmProspect,
    Installment,
    InsuranceLine,
    Party,
    PartyRole,
    PaymentPlan,
    Policy,
    PolicyTerm,
    PublicQuote,
    PublicQuoteTraveler,
    PublicSalesChannel,
)
from corredores.domain.public_channel_constants import QUOTE_COMPLETED, QUOTE_PAID
from corredores.services.auto_e2e import generate_proposed_installments, suggest_policy_term
from corredores.services.crm_service import (
    CrmAmbiguousCustomer,
    CrmError,
    convert_opportunity_to_customer,
)
from corredores.services.producer_portfolio import assign_policy_primary

# Prefer these carriers when channel has no default; first active match wins.
_CARRIER_PREF = ("ASSA", "SURA", "MAPFRE", "ANCON", "FEDPA")


class PublicIssuanceError(Exception):
    """Cannot materialize Party/Policy from paid public quote."""


def ensure_viaje_line(session: Session) -> InsuranceLine:
    line = session.query(InsuranceLine).filter_by(code="VIAJE").one_or_none()
    if line is None:
        line = InsuranceLine(code="VIAJE", name="Seguro de viaje", operational_in_p0=False)
        session.add(line)
        session.flush()
    return line


def _resolve_carrier(session: Session, organization_id: str) -> Carrier:
    q = session.query(Carrier).filter_by(organization_id=organization_id, active=True)
    for code in _CARRIER_PREF:
        c = q.filter_by(code=code).one_or_none()
        if c:
            return c
    c = q.order_by(Carrier.code).first()
    if c is None:
        raise PublicIssuanceError("la organización no tiene aseguradoras activas")
    return c


def _policy_number(quote: PublicQuote) -> str:
    plan = (quote.selected_plan_code or "PLAN").upper()[:12]
    return f"AV-{quote.public_token[:8].upper()}-{plan}"


def _primary_traveler(session: Session, quote: PublicQuote) -> PublicQuoteTraveler | None:
    tr = (
        session.query(PublicQuoteTraveler)
        .filter_by(quote_id=quote.id, is_primary=True)
        .one_or_none()
    )
    if tr:
        return tr
    return (
        session.query(PublicQuoteTraveler)
        .filter_by(quote_id=quote.id)
        .order_by(PublicQuoteTraveler.seq)
        .first()
    )


def _ensure_client_role(session: Session, *, organization_id: str, party_id: str) -> None:
    role = (
        session.query(PartyRole)
        .filter_by(
            organization_id=organization_id,
            party_id=party_id,
            role_type=PartyRoleType.CLIENT,
            context_type="GLOBAL",
        )
        .first()
    )
    if role is None:
        session.add(
            PartyRole(
                organization_id=organization_id,
                party_id=party_id,
                role_type=PartyRoleType.CLIENT,
                context_type="GLOBAL",
                context_id=None,
            )
        )


def _party_from_traveler(
    session: Session,
    quote: PublicQuote,
    traveler: PublicQuoteTraveler,
    *,
    actor_id: str,
) -> Party:
    party = Party(
        organization_id=quote.organization_id,
        party_type=PartyType.PERSON,
        first_name=traveler.first_name,
        last_name=traveler.last_name,
        national_id=traveler.identification_number,
        phone=traveler.phone,
        email=(traveler.email or "").lower() or None,
        birth_date=traveler.birth_date,
        data_source=DataSource.PORTAL,
    )
    session.add(party)
    session.flush()
    _ensure_client_role(session, organization_id=quote.organization_id, party_id=party.id)
    if quote.crm_prospect_id:
        prosp = session.get(CrmProspect, quote.crm_prospect_id)
        if prosp and prosp.organization_id == quote.organization_id:
            prosp.converted_customer_id = party.id
            prosp.status = PROSPECT_CONVERTED
    if quote.crm_opportunity_id:
        opp = session.get(CrmOpportunity, quote.crm_opportunity_id)
        if opp and opp.organization_id == quote.organization_id:
            opp.customer_id = party.id
    session.add(
        AuditEvent(
            organization_id=quote.organization_id,
            actor_id=actor_id,
            entity_type="Party",
            entity_id=party.id,
            action="PUBLIC_CHANNEL_PARTY_CREATED",
            detail_json=json.dumps({"quote_id": quote.id, "source": "traveler"}, ensure_ascii=False),
        )
    )
    session.flush()
    return party


def ensure_party_for_paid_quote(
    session: Session,
    quote: PublicQuote,
    *,
    actor_id: str,
) -> Party:
    if quote.party_id:
        party = session.get(Party, quote.party_id)
        if party and party.organization_id == quote.organization_id:
            return party

    if quote.crm_opportunity_id:
        try:
            _opp, party, _action = convert_opportunity_to_customer(
                session,
                None,
                organization_id=quote.organization_id,
                opportunity_id=quote.crm_opportunity_id,
                actor_id=actor_id,
            )
            # Prefer PORTAL source for channel-born clients
            if party.data_source == DataSource.MANUAL:
                party.data_source = DataSource.PORTAL
            _ensure_client_role(
                session, organization_id=quote.organization_id, party_id=party.id
            )
            quote.party_id = party.id
            session.flush()
            return party
        except CrmAmbiguousCustomer:
            # Do not guess among matches — create a clean Party from traveler
            pass
        except CrmError:
            pass

    traveler = _primary_traveler(session, quote)
    if traveler is None:
        raise PublicIssuanceError("no hay pasajero titular para crear el cliente")
    party = _party_from_traveler(session, quote, traveler, actor_id=actor_id)
    quote.party_id = party.id
    session.flush()
    return party


def _create_policy(
    session: Session,
    quote: PublicQuote,
    party: Party,
    channel: PublicSalesChannel,
    *,
    actor_id: str,
) -> Policy:
    line = ensure_viaje_line(session)
    carrier = _resolve_carrier(session, quote.organization_id)
    number = _policy_number(quote)

    existing = (
        session.query(Policy)
        .filter_by(
            organization_id=quote.organization_id,
            carrier_id=carrier.id,
            insurance_line_id=line.id,
            policy_number=number,
        )
        .one_or_none()
    )
    if existing:
        return existing

    premium = Decimal(str(quote.selected_premium or 0)).quantize(Decimal("0.01"))
    if premium <= 0:
        raise PublicIssuanceError("prima inválida para emitir póliza")

    eff = quote.start_date or (quote.paid_at.date() if quote.paid_at else date.today())
    exp = quote.end_date
    eff, exp, term_src = suggest_policy_term(
        eff, term_source=TermSource.MANUAL, expiration_date=exp
    )

    snap: dict[str, Any] = {}
    if quote.selected_plan_snapshot_json:
        try:
            snap = json.loads(quote.selected_plan_snapshot_json) or {}
        except json.JSONDecodeError:
            snap = {}

    policy = Policy(
        organization_id=quote.organization_id,
        carrier_id=carrier.id,
        insurance_line_id=line.id,
        client_party_id=party.id,
        policy_number=number,
        status=PolicyStatus.ACTIVE,
        net_premium=premium,
        gross_premium=premium,
        annual_premium=premium,
        data_source=DataSource.PORTAL,
    )
    session.add(policy)
    session.flush()

    session.add(
        PolicyTerm(
            policy_id=policy.id,
            effective_date=eff,
            expiration_date=exp,
            term_source=term_src,
        )
    )
    plan = PaymentPlan(
        policy_id=policy.id,
        confirmed=True,
        notes=(
            f"Canal público {channel.slug} · plan {quote.selected_plan_code or snap.get('name') or '—'} "
            f"· {quote.origin or ''}→{quote.destination or quote.destination_region or ''} "
            f"· quote {quote.public_token[:8]}"
        )[:500],
    )
    session.add(plan)
    session.flush()

    due = quote.paid_at.date() if quote.paid_at else date.today()
    for num, due_d, amount in generate_proposed_installments(
        start_due=due, count=1, total_amount=premium
    ):
        session.add(
            Installment(
                payment_plan_id=plan.id,
                installment_number=num,
                due_date=due_d,
                amount=amount,
                due_date_source=DueDateSource.SYSTEM_GENERATED,
            )
        )

    if channel.default_producer_profile_id:
        try:
            assign_policy_primary(
                session,
                organization_id=quote.organization_id,
                producer_profile_id=channel.default_producer_profile_id,
                policy_id=policy.id,
                effective_from=eff,
                reason=f"canal público {channel.slug}",
                assigned_by_subject_id=actor_id,
            )
        except Exception:
            pass

    session.add(
        AuditEvent(
            organization_id=quote.organization_id,
            actor_id=actor_id,
            entity_type="Policy",
            entity_id=policy.id,
            action="PUBLIC_CHANNEL_POLICY_ISSUED",
            detail_json=json.dumps(
                {
                    "quote_id": quote.id,
                    "policy_number": number,
                    "plan_code": quote.selected_plan_code,
                    "carrier_id": carrier.id,
                    "premium": str(premium),
                },
                ensure_ascii=False,
            ),
        )
    )
    session.flush()
    return policy


def issue_party_and_policy_from_paid_quote(
    session: Session,
    quote: PublicQuote,
    *,
    actor_id: str | None = None,
) -> tuple[Party, Policy]:
    """Idempotent: PAID quote → Party + VIAJE Policy under quote.organization_id."""
    if quote.status not in (QUOTE_PAID, QUOTE_COMPLETED) and quote.payment_status != "SUCCEEDED":
        raise PublicIssuanceError("la cotización debe estar pagada")

    actor = actor_id or f"public_channel:{quote.channel_id}"
    channel = session.get(PublicSalesChannel, quote.channel_id)
    if channel is None or channel.organization_id != quote.organization_id:
        raise PublicIssuanceError("canal inválido")

    if quote.policy_id:
        policy = session.get(Policy, quote.policy_id)
        party = session.get(Party, quote.party_id) if quote.party_id else None
        if policy and party:
            if quote.status == QUOTE_PAID:
                quote.status = QUOTE_COMPLETED
                session.flush()
            return party, policy

    party = ensure_party_for_paid_quote(session, quote, actor_id=actor)
    policy = _create_policy(session, quote, party, channel, actor_id=actor)
    quote.party_id = party.id
    quote.policy_id = policy.id
    quote.status = QUOTE_COMPLETED
    session.flush()
    return party, policy
