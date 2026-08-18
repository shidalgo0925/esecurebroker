"""SQLAlchemy domain models — P0 AUTO E2E.

Domain Truth: parties, submission, policy/term, payment plan facts,
payments, commission snapshots, audit.
Derived (not primary truth): PENDING/DUE/OVERDUE installment views.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corredores.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Organization(Base, TimestampMixin):
    """Tenant row inside Corredores DB (links to EN1 org when ADR-006 lands)."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    external_en1_org_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Identidad de correduría (Configuración) — cabecera de PDF / documentos
    legal_name: Mapped[Optional[str]] = mapped_column(String(200))
    trade_name: Mapped[Optional[str]] = mapped_column(String(200))
    tax_id: Mapped[Optional[str]] = mapped_column(String(64))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    website: Mapped[Optional[str]] = mapped_column(String(200))
    address: Mapped[Optional[str]] = mapped_column(Text)
    slogan: Mapped[Optional[str]] = mapped_column(String(240))
    document_footer: Mapped[Optional[str]] = mapped_column(String(500))
    logo_relpath: Mapped[Optional[str]] = mapped_column(String(500))


class Party(Base, TimestampMixin):
    __tablename__ = "parties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    party_type: Mapped[str] = mapped_column(String(32), nullable=False)  # PERSON|ORGANIZATION
    first_name: Mapped[Optional[str]] = mapped_column(String(120))
    last_name: Mapped[Optional[str]] = mapped_column(String(120))
    legal_name: Mapped[Optional[str]] = mapped_column(String(200))
    trade_name: Mapped[Optional[str]] = mapped_column(String(200))
    national_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    district: Mapped[Optional[str]] = mapped_column(String(80))
    address: Mapped[Optional[str]] = mapped_column(Text)
    birth_date: Mapped[Optional[date]] = mapped_column(Date)
    data_source: Mapped[str] = mapped_column(String(32), default="MANUAL")
    # ADR-008: optional default for new policies / import — NOT portfolio ownership.
    # FK enforced in Alembic (Postgres); no ORM FK here to avoid circular create/drop.
    default_producer_profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )


class PartyRole(Base, TimestampMixin):
    __tablename__ = "party_roles"
    __table_args__ = (UniqueConstraint("party_id", "role_type", "context_type", "context_id", name="uq_party_role_ctx"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    role_type: Mapped[str] = mapped_column(String(32), nullable=False)
    context_type: Mapped[Optional[str]] = mapped_column(String(32))  # POLICY|SUBMISSION|GLOBAL
    context_id: Mapped[Optional[str]] = mapped_column(String(36))


class Carrier(Base, TimestampMixin):
    __tablename__ = "carriers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_carrier_org_code"),)


class InsuranceLine(Base, TimestampMixin):
    __tablename__ = "insurance_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    operational_in_p0: Mapped[bool] = mapped_column(Boolean, default=False)  # True only for AUTO


class CarrierProduct(Base, TimestampMixin):
    __tablename__ = "carrier_products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    carrier_id: Mapped[str] = mapped_column(ForeignKey("carriers.id"), index=True)
    insurance_line_id: Mapped[str] = mapped_column(ForeignKey("insurance_lines.id"), index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class CarrierCapability(Base, TimestampMixin):
    """Modeled in P0 — no external adapters yet."""

    __tablename__ = "carrier_capabilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    carrier_id: Mapped[str] = mapped_column(ForeignKey("carriers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Submission(Base, TimestampMixin):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    client_party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    carrier_id: Mapped[Optional[str]] = mapped_column(ForeignKey("carriers.id"))
    insurance_line_id: Mapped[str] = mapped_column(ForeignKey("insurance_lines.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    data_source: Mapped[str] = mapped_column(String(32), default="MANUAL")


class VehicleRisk(Base, TimestampMixin):
    """AUTO specialization — core Policy stays line-agnostic."""

    __tablename__ = "vehicle_risks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    submission_id: Mapped[Optional[str]] = mapped_column(ForeignKey("submissions.id"))
    policy_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)  # set after policy exists
    make: Mapped[Optional[str]] = mapped_column(String(80))
    model: Mapped[Optional[str]] = mapped_column(String(80))
    year: Mapped[Optional[int]] = mapped_column(Integer)
    plate: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    vehicle_type: Mapped[Optional[str]] = mapped_column(String(40))
    usage: Mapped[Optional[str]] = mapped_column(String(40))  # PARTICULAR|COMERCIAL


class Policy(Base, TimestampMixin):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    submission_id: Mapped[Optional[str]] = mapped_column(ForeignKey("submissions.id"), index=True)
    carrier_id: Mapped[str] = mapped_column(ForeignKey("carriers.id"), index=True)
    insurance_line_id: Mapped[str] = mapped_column(ForeignKey("insurance_lines.id"), index=True)
    carrier_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("carrier_products.id"))
    policy_number: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING_EFFECTIVE")
    client_party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    net_premium: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    gross_premium: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    annual_premium: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text)
    cancellation_effective_date: Mapped[Optional[date]] = mapped_column(Date)
    data_source: Mapped[str] = mapped_column(String(32), default="MANUAL")

    term: Mapped[Optional["PolicyTerm"]] = relationship(back_populates="policy", uselist=False)
    payment_plan: Mapped[Optional["PaymentPlan"]] = relationship(back_populates="policy", uselist=False)


class PolicyTerm(Base, TimestampMixin):
    """Contractual term — independent from PaymentPlan (D-05)."""

    __tablename__ = "policy_terms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), unique=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    term_source: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")

    policy: Mapped[Policy] = relationship(back_populates="term")


class PaymentPlan(Base, TimestampMixin):
    __tablename__ = "payment_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), unique=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    policy: Mapped[Policy] = relationship(back_populates="payment_plan")
    installments: Mapped[list["Installment"]] = relationship(back_populates="payment_plan")


class Installment(Base, TimestampMixin):
    """Facts only: number, due_date, amount, cancelled_at. Status is derived (D-19)."""

    __tablename__ = "installments"
    __table_args__ = (UniqueConstraint("payment_plan_id", "installment_number", name="uq_installment_num"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    payment_plan_id: Mapped[str] = mapped_column(ForeignKey("payment_plans.id"), index=True)
    installment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    due_date_source: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    payment_plan: Mapped[PaymentPlan] = relationship(back_populates="installments")
    allocations: Mapped[list["PaymentAllocation"]] = relationship(back_populates="installment")


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[Optional[str]] = mapped_column(String(40))
    reference: Mapped[Optional[str]] = mapped_column(String(120))
    data_source: Mapped[str] = mapped_column(String(32), default="MANUAL")

    allocations: Mapped[list["PaymentAllocation"]] = relationship(back_populates="payment")


class PaymentAllocation(Base, TimestampMixin):
    __tablename__ = "payment_allocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    installment_id: Mapped[str] = mapped_column(ForeignKey("installments.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    payment: Mapped[Payment] = relationship(back_populates="allocations")
    installment: Mapped[Installment] = relationship(back_populates="allocations")


class CommissionRule(Base, TimestampMixin):
    __tablename__ = "commission_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    carrier_id: Mapped[Optional[str]] = mapped_column(ForeignKey("carriers.id"))
    insurance_line_id: Mapped[Optional[str]] = mapped_column(ForeignKey("insurance_lines.id"))
    carrier_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("carrier_products.id"))
    rate: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    calculation_base: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    agreement_reference: Mapped[Optional[str]] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(32), default="MANUAL")


class CommissionSplitRule(Base, TimestampMixin):
    __tablename__ = "commission_split_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    broker_share: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))
    office_share: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))
    executive_share: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))
    referral_share: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)


class Commission(Base, TimestampMixin):
    """Snapshot of applied calculation — immutable history (D-18)."""

    __tablename__ = "commissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("commission_rules.id"))
    calculation_base: Mapped[str] = mapped_column(String(32), nullable=False)
    base_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    calculated_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommissionSplit(Base, TimestampMixin):
    __tablename__ = "commission_splits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    commission_id: Mapped[str] = mapped_column(ForeignKey("commissions.id"), index=True)
    split_rule_id: Mapped[Optional[str]] = mapped_column(ForeignKey("commission_split_rules.id"))
    broker_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    office_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    executive_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    referral_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))


class RenewalOpportunity(Base, TimestampMixin):
    __tablename__ = "renewal_opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    previous_policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), index=True)
    new_policy_id: Mapped[Optional[str]] = mapped_column(ForeignKey("policies.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="UPCOMING")
    target_date: Mapped[Optional[date]] = mapped_column(Date)


class QuoteRequest(Base, TimestampMixin):
    __tablename__ = "quote_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    submission_id: Mapped[Optional[str]] = mapped_column(ForeignKey("submissions.id"))
    insurance_line_id: Mapped[str] = mapped_column(ForeignKey("insurance_lines.id"))
    payload_json: Mapped[Optional[str]] = mapped_column(Text)


class CarrierQuoteRequest(Base, TimestampMixin):
    __tablename__ = "carrier_quote_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_request_id: Mapped[str] = mapped_column(ForeignKey("quote_requests.id"), index=True)
    carrier_id: Mapped[str] = mapped_column(ForeignKey("carriers.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")


class NormalizedQuote(Base, TimestampMixin):
    __tablename__ = "normalized_quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    carrier_quote_request_id: Mapped[str] = mapped_column(ForeignKey("carrier_quote_requests.id"), index=True)
    premium: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    raw_ref: Mapped[Optional[str]] = mapped_column(String(200))


class IntegrationEvent(Base, TimestampMixin):
    __tablename__ = "integration_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), default="OUT")
    payload_json: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="RECORDED")


class AuditEvent(Base, TimestampMixin):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    detail_json: Mapped[Optional[str]] = mapped_column(Text)


class PaymentPromise(Base, TimestampMixin):
    """Domain Truth for promised payment — cobranza bands (UX)."""

    __tablename__ = "payment_promises"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), index=True)
    installment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("installments.id"), index=True)
    party_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parties.id"), index=True)
    promised_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    promised_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    comment: Mapped[Optional[str]] = mapped_column(Text)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Interaction(Base, TimestampMixin):
    """Replaces Excel 'GESTIONADO' pseudo-status — activity log."""

    __tablename__ = "interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    party_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parties.id"), index=True)
    policy_id: Mapped[Optional[str]] = mapped_column(ForeignKey("policies.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="NOTE")  # NOTE|CALL|EMAIL|WHATSAPP|VISIT|OTHER
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(String(64))
    data_source: Mapped[str] = mapped_column(String(32), default="MANUAL")
    # Mobile F5A idempotency (nullable; unique per org when set)
    client_activity_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="OPEN")  # OPEN|DONE|CANCELLED
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    party_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parties.id"))
    policy_id: Mapped[Optional[str]] = mapped_column(ForeignKey("policies.id"))
    related_type: Mapped[Optional[str]] = mapped_column(String(64))
    related_id: Mapped[Optional[str]] = mapped_column(String(36))
    actor_id: Mapped[Optional[str]] = mapped_column(String(64))


class Claim(Base, TimestampMixin):
    """Modeled for SERVICE/portal hooks — full claims UI not P0 runtime focus."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), index=True)
    party_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parties.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="REPORTED")
    claim_number: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    loss_date: Mapped[Optional[date]] = mapped_column(Date)
    description: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="BROKER")  # BROKER|PORTAL|SYSTEM
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class RecommendationRecord(Base, TimestampMixin):
    """AI/NBA suggestion lifecycle — never Domain Truth for money/policy."""

    __tablename__ = "recommendation_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[Optional[str]] = mapped_column(Text)
    decision: Mapped[Optional[str]] = mapped_column(String(32))  # ACCEPTED|DISCARDED|POSTPONED
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[Optional[str]] = mapped_column(String(64))


class Document(Base, TimestampMixin):
    """Client/policy PDF attachments — binary on disk, metadata in Domain Truth."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    party_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parties.id"), index=True)
    policy_id: Mapped[Optional[str]] = mapped_column(ForeignKey("policies.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/pdf")
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    doc_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="OTRO")
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(64))
    data_source: Mapped[str] = mapped_column(String(32), default="MANUAL")
    # Mobile F5A idempotency
    client_upload_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64))


class StatementDelivery(Base, TimestampMixin):
    """Log of account-statement sends (manual or auto) — idempotency + audit."""

    __tablename__ = "statement_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="EMAIL")
    trigger: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")  # MANUAL|AUTO
    to_email: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="SENT")  # SENT|SKIPPED|FAILED
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    overdue_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    open_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    actor_id: Mapped[Optional[str]] = mapped_column(String(64))


class OrgMembership(Base, TimestampMixin):
    """Subject ↔ Organization (ADR-007/008).

    role_code: system OWNER|ADMIN|BROKER|PRODUCER|COLLECTIONS|PLATFORM or custom org role code.
    status (F7): INVITED|ACTIVE|INACTIVE|REVOKED — source of truth; ``active`` synced (ACTIVE only).
    """

    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("subject_id", "organization_id", name="uq_org_membership_subject_org"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Optional display for piloto; EN1 will own profile later
    display_name: Mapped[Optional[str]] = mapped_column(String(200))
    email: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False, default="BROKER")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    producer_profile_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("producer_profiles.id"), nullable=True, index=True
    )
    invited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    invited_by_subject_id: Mapped[Optional[str]] = mapped_column(String(128))
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_by_subject_id: Mapped[Optional[str]] = mapped_column(String(128))
    last_access_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    external_en1_membership_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True)


class OrgRole(Base, TimestampMixin):
    """System (organization_id NULL) or custom tenant role (ADR-008 F7)."""

    __tablename__ = "org_roles"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_org_role_org_code"),
        Index("ix_org_roles_system_code", "code", unique=False),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    system_role: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="ORGANIZATION")


class OrgRolePermission(Base, TimestampMixin):
    """Permission grant on a Role (primarily custom roles)."""

    __tablename__ = "org_role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_code", name="uq_org_role_permission"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    role_id: Mapped[str] = mapped_column(ForeignKey("org_roles.id"), index=True, nullable=False)
    permission_code: Mapped[str] = mapped_column(String(64), nullable=False)


class OrgInvitation(Base, TimestampMixin):
    """Opaque invite token (hashed) for collaborator onboarding (ADR-008 F7)."""

    __tablename__ = "org_invitations"
    __table_args__ = (
        Index("ix_org_invitations_org_email", "organization_id", "email"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    membership_id: Mapped[str] = mapped_column(ForeignKey("org_memberships.id"), index=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")  # PENDING|ACCEPTED|REVOKED|EXPIRED
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_subject_id: Mapped[Optional[str]] = mapped_column(String(128))
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ProducerProfile(Base, TimestampMixin):
    """Domain producer/agent inside an Organization (ADR-008). Membership optional."""

    __tablename__ = "producer_profiles"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_producer_profile_org_code"),
        UniqueConstraint("organization_id", "party_id", name="uq_producer_profile_org_party"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    code: Mapped[Optional[str]] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")


class PortfolioAssignment(Base, TimestampMixin):
    """Versioned portfolio ownership (ADR-008). P0 operational: POLICY + PRIMARY."""

    __tablename__ = "portfolio_assignments"
    __table_args__ = (
        Index(
            "uq_portfolio_primary_policy_active",
            "organization_id",
            "target_id",
            unique=True,
            sqlite_where=text(
                "target_type = 'POLICY' AND assignment_role = 'PRIMARY' AND effective_to IS NULL"
            ),
            postgresql_where=text(
                "target_type = 'POLICY' AND assignment_role = 'PRIMARY' AND effective_to IS NULL"
            ),
        ),
        Index("ix_portfolio_assignments_producer", "organization_id", "producer_profile_id"),
        Index(
            "ix_portfolio_assignments_target",
            "organization_id",
            "target_type",
            "target_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    producer_profile_id: Mapped[str] = mapped_column(
        ForeignKey("producer_profiles.id"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)  # POLICY|PARTY
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assignment_role: Mapped[str] = mapped_column(String(32), nullable=False, default="PRIMARY")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date)
    reason: Mapped[Optional[str]] = mapped_column(String(500))
    assigned_by_subject_id: Mapped[Optional[str]] = mapped_column(String(128))


class BrokerAccount(Base, TimestampMixin):
    """Cuenta self-serve del corredor (piloto hasta identidad EN1 / ADR-006).

    No sustituye el control plane de EN1; permite registro+login local mientras tanto.
    """

    __tablename__ = "broker_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class OrgSubscription(Base, TimestampMixin):
    """Suscripción SaaS de la organización (piloto; billing definitivo → EN1)."""

    __tablename__ = "org_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, unique=True, index=True
    )
    plan_code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )  # pending|active|past_due|canceled
    billing_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="piloto")
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(64))
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(64))
    stripe_checkout_session_id: Mapped[Optional[str]] = mapped_column(String(128))
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # ADR-008 F5 — optional EN1 compound seat limits (None = unlimited when source=en1)
    seats_limits_source: Mapped[Optional[str]] = mapped_column(String(32))  # en1 | None
    internal_seats_limit: Mapped[Optional[int]] = mapped_column(Integer)
    producer_seats_limit: Mapped[Optional[int]] = mapped_column(Integer)


class SaasPaymentReceipt(Base, TimestampMixin):
    """Comprobante transferencia/Yappy SaaS — cola de verificación (plataforma)."""

    __tablename__ = "saas_payment_receipts"
    __table_args__ = (Index("ix_saas_receipts_status_created", "verification_status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    subscription_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("org_subscriptions.id"), nullable=True, index=True
    )
    plan_code: Mapped[str] = mapped_column(String(40), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)  # transfer | yappy
    payment_reference: Mapped[Optional[str]] = mapped_column(String(120))
    amount_usd: Mapped[Optional[int]] = mapped_column(Integer)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reported_by: Mapped[Optional[str]] = mapped_column(String(200))
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )  # pending|approved|rejected
    reviewer_subject_id: Mapped[Optional[str]] = mapped_column(String(128))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[Optional[str]] = mapped_column(String(500))


class MobileRefreshToken(Base, TimestampMixin):
    """Refresh tokens for ESB GO Mobile API (Gate B). Opaque token hashed at rest."""

    __tablename__ = "mobile_refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(200), nullable=False)
    organization_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[Optional[str]] = mapped_column(String(36))


class CarrierIncentivePlan(Base, TimestampMixin):
    """ADR-009 — acuerdo Organization→Carrier de beneficio por producción/cobranza.

    Distinto de comisión ordinaria (CommissionRule). Lifecycle de beneficio:
    ESTIMATED → EARNED (cálculo ESB) vs CLAIMED → RECOGNIZED → PAID (settlement).
    """

    __tablename__ = "carrier_incentive_plans"
    __table_args__ = (
        Index("ix_cip_org_carrier", "organization_id", "carrier_id"),
        Index("ix_cip_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    carrier_id: Mapped[str] = mapped_column(ForeignKey("carriers.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    metric_type: Mapped[str] = mapped_column(String(32), nullable=False)  # COLLECTION|PRODUCTION
    period_type: Mapped[str] = mapped_column(String(32), nullable=False, default="CUSTOM")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    calculation_base: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    # Snapshot lock: when True, tier/scope edits that affect closed settlements are blocked
    conditions_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CarrierIncentiveScope(Base, TimestampMixin):
    """Alcance del plan: carrier completo, ramo(s), producto(s), agent code(s)."""

    __tablename__ = "carrier_incentive_scopes"
    __table_args__ = (
        Index("ix_cis_plan", "plan_id"),
        UniqueConstraint(
            "plan_id",
            "scope_kind",
            "insurance_line_id",
            "carrier_product_id",
            "agent_code",
            name="uq_cis_plan_scope_target",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("carrier_incentive_plans.id"), index=True)
    scope_kind: Mapped[str] = mapped_column(String(32), nullable=False)  # CARRIER|LINE|PRODUCT|AGENT_CODE
    insurance_line_id: Mapped[Optional[str]] = mapped_column(ForeignKey("insurance_lines.id"))
    carrier_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("carrier_products.id"))
    agent_code: Mapped[Optional[str]] = mapped_column(String(64))  # CarrierAgentCode — ≠ Producer


class CarrierIncentiveTier(Base, TimestampMixin):
    """Tramo de beneficio (meta → % o monto fijo)."""

    __tablename__ = "carrier_incentive_tiers"
    __table_args__ = (
        UniqueConstraint("plan_id", "sequence", name="uq_cit_plan_sequence"),
        Index("ix_cit_plan", "plan_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("carrier_incentive_plans.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    threshold_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    benefit_type: Mapped[str] = mapped_column(String(32), nullable=False)  # PERCENTAGE|FIXED_AMOUNT
    benefit_value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # For PERCENTAGE: value is percent points (2 = 2%). For FIXED: currency amount.
    calculation_base: Mapped[Optional[str]] = mapped_column(String(40))  # override plan base if set


class CarrierIncentiveEligibleTxn(Base, TimestampMixin):
    """Movimiento trazable que alimenta el acumulado del plan. No DELETE — usar REVERSED."""

    __tablename__ = "carrier_incentive_eligible_txns"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "source_type",
            "source_id",
            name="uq_cie_plan_source",
        ),
        Index("ix_cie_plan_status", "plan_id", "confirmation_status"),
        Index("ix_cie_org_policy", "organization_id", "policy_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("carrier_incentive_plans.id"), index=True)
    policy_id: Mapped[Optional[str]] = mapped_column(ForeignKey("policies.id"), index=True)
    payment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("payments.id"), index=True)
    insurance_line_id: Mapped[Optional[str]] = mapped_column(ForeignKey("insurance_lines.id"))
    carrier_id: Mapped[str] = mapped_column(ForeignKey("carriers.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)  # PAYMENT|PRODUCTION|MANUAL
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    agent_code: Mapped[Optional[str]] = mapped_column(String(64))
    carrier_receipt_number: Mapped[Optional[str]] = mapped_column(String(120))
    confirmation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    # PENDING → CONFIRMED → REVERSED (never delete)
    reversed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reverse_reason: Mapped[Optional[str]] = mapped_column(String(500))
    notes: Mapped[Optional[str]] = mapped_column(Text)


class CarrierIncentiveSettlement(Base, TimestampMixin):
    """Liquidación del beneficio: CALCULATED→CLAIMED→RECOGNIZED→PAID (+ excepciones)."""

    __tablename__ = "carrier_incentive_settlements"
    __table_args__ = (
        Index("ix_ciset_plan_status", "plan_id", "status"),
        UniqueConstraint("plan_id", "period_label", name="uq_ciset_plan_period"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("carrier_incentive_plans.id"), index=True)
    period_label: Mapped[str] = mapped_column(String(80), nullable=False)  # e.g. 2026 / 2026-H1
    eligible_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    calculated_benefit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    benefit_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="ESTIMATED")
    # ESTIMATED|EARNED — ESB calc only; never auto → RECOGNIZED
    claimed_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    recognized_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    recognized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CALCULATED")
    carrier_reference: Mapped[Optional[str]] = mapped_column(String(120))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CarrierIncentiveEvidence(Base, TimestampMixin):
    """Evidencia documental asociada a plan o settlement (ruta en disco + metadatos)."""

    __tablename__ = "carrier_incentive_evidence"
    __table_args__ = (Index("ix_ciev_plan", "plan_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("carrier_incentive_plans.id"), index=True)
    settlement_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("carrier_incentive_settlements.id"), index=True
    )
    document_id: Mapped[Optional[str]] = mapped_column(ForeignKey("documents.id"))
    evidence_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="OTRO")
    # CONTRATO|CARTA|CORREO|TABLA|LIQUIDACION|COMPROBANTE|PAGO|OTRO
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    stored_path: Mapped[Optional[str]] = mapped_column(String(500))
    original_filename: Mapped[Optional[str]] = mapped_column(String(255))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(128))


# =============================================================================
# ADR-011 — ESB CRM (new-business). Distinct from RenewalOpportunity / Interaction.
# Tables prefixed crm_* to avoid collisions with renewal “oportunidades”.
# =============================================================================


class CrmLeadSource(Base, TimestampMixin):
    """Origen de prospecto — catálogo por Organization (ADR-011)."""

    __tablename__ = "crm_lead_sources"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_crm_lead_source_org_code"),
        Index("ix_crm_lead_sources_org", "organization_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)


class CrmLostReason(Base, TimestampMixin):
    """Motivo de oportunidad perdida — catálogo por Organization (ADR-011)."""

    __tablename__ = "crm_lost_reasons"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_crm_lost_reason_org_code"),
        Index("ix_crm_lost_reasons_org", "organization_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)


class CrmPipelineStage(Base, TimestampMixin):
    """Etapa de pipeline estándar ESB (P0); futuro: pipelines personalizados."""

    __tablename__ = "crm_pipeline_stages"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_crm_pipeline_stage_org_code"),
        UniqueConstraint("organization_id", "sequence", name="uq_crm_pipeline_stage_org_seq"),
        Index("ix_crm_pipeline_stages_org", "organization_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    is_won: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_lost: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_kanban: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CrmProspect(Base, TimestampMixin):
    """Interesado comercial — NO es Customer (Party+CLIENT). ADR-011 invariante #1."""

    __tablename__ = "crm_prospects"
    __table_args__ = (
        Index("ix_crm_prospects_org_status", "organization_id", "status"),
        Index("ix_crm_prospects_org_email", "organization_id", "email"),
        Index("ix_crm_prospects_org_phone", "organization_id", "phone"),
        Index("ix_crm_prospects_org_mobile", "organization_id", "mobile"),
        Index("ix_crm_prospects_org_idnum", "organization_id", "identification_number"),
        Index("ix_crm_prospects_assigned_producer", "organization_id", "assigned_producer_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    prospect_type: Mapped[str] = mapped_column(String(32), nullable=False, default="PERSON")
    first_name: Mapped[Optional[str]] = mapped_column(String(120))
    last_name: Mapped[Optional[str]] = mapped_column(String(120))
    company_name: Mapped[Optional[str]] = mapped_column(String(200))
    identification_type: Mapped[Optional[str]] = mapped_column(String(40))
    identification_number: Mapped[Optional[str]] = mapped_column(String(64))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    mobile: Mapped[Optional[str]] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    source_id: Mapped[Optional[str]] = mapped_column(ForeignKey("crm_lead_sources.id"), index=True)
    referral_source_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parties.id"), index=True)
    assigned_producer_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("producer_profiles.id"), index=True
    )
    assigned_executive_id: Mapped[Optional[str]] = mapped_column(String(128))  # subject_id
    # Office entity not yet in ESB — nullable soft ref (gap documented ADR-011 F1)
    office_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    # Set when converted/linked to Customer (Party); Prospect row is retained
    converted_customer_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parties.id"), index=True)


class CrmOpportunity(Base, TimestampMixin):
    """Oportunidad comercial new-business. ≠ RenewalOpportunity. ≠ Quotation. ≠ Policy.

    May attach to Prospect and/or existing Customer (Party). At least one required (DB check).
    """

    __tablename__ = "crm_opportunities"
    __table_args__ = (
        Index("ix_crm_opp_org_stage", "organization_id", "stage_code"),
        Index("ix_crm_opp_org_prospect", "organization_id", "prospect_id"),
        Index("ix_crm_opp_org_customer", "organization_id", "customer_id"),
        Index("ix_crm_opp_assigned_producer", "organization_id", "assigned_producer_id"),
        Index("ix_crm_opp_next_activity", "organization_id", "next_activity_at"),
        CheckConstraint(
            "prospect_id IS NOT NULL OR customer_id IS NOT NULL",
            name="ck_crm_opp_prospect_or_customer",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    prospect_id: Mapped[Optional[str]] = mapped_column(ForeignKey("crm_prospects.id"), index=True)
    customer_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parties.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    line_of_business_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("insurance_lines.id"), index=True
    )
    product_interest: Mapped[Optional[str]] = mapped_column(String(200))
    carrier_id: Mapped[Optional[str]] = mapped_column(ForeignKey("carriers.id"), index=True)
    assigned_producer_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("producer_profiles.id"), index=True
    )
    assigned_executive_id: Mapped[Optional[str]] = mapped_column(String(128))
    office_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    stage_id: Mapped[Optional[str]] = mapped_column(ForeignKey("crm_pipeline_stages.id"), index=True)
    stage_code: Mapped[str] = mapped_column(String(40), nullable=False, default="NEW")
    estimated_premium: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    probability: Mapped[Optional[int]] = mapped_column(Integer)  # 0–100
    expected_close_date: Mapped[Optional[date]] = mapped_column(Date)
    next_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[Optional[str]] = mapped_column(ForeignKey("crm_lead_sources.id"), index=True)
    referral_source_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parties.id"), index=True)
    lost_reason_id: Mapped[Optional[str]] = mapped_column(ForeignKey("crm_lost_reasons.id"), index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    won_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    lost_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reopened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[str]] = mapped_column(String(128))


class CrmActivity(Base, TimestampMixin):
    """Actividad operativa CRM (llamar, WhatsApp, seguimiento…).

    Distinct from `interactions` (activity log / mobile F5A) and `tasks`.
    OVERDUE may be stored or derived from PENDING + due_at < now (service later).
    """

    __tablename__ = "crm_activities"
    __table_args__ = (
        Index("ix_crm_act_org_status", "organization_id", "status"),
        Index("ix_crm_act_org_due", "organization_id", "due_at"),
        Index("ix_crm_act_opportunity", "organization_id", "opportunity_id"),
        Index("ix_crm_act_prospect", "organization_id", "prospect_id"),
        Index("ix_crm_act_assignee", "organization_id", "assignee_subject_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    opportunity_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("crm_opportunities.id"), index=True
    )
    prospect_id: Mapped[Optional[str]] = mapped_column(ForeignKey("crm_prospects.id"), index=True)
    activity_type: Mapped[str] = mapped_column(String(40), nullable=False, default="FOLLOW_UP")
    title: Mapped[Optional[str]] = mapped_column(String(200))
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    result: Mapped[Optional[str]] = mapped_column(String(200))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    assignee_subject_id: Mapped[Optional[str]] = mapped_column(String(128))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[str]] = mapped_column(String(128))


class SystemSetting(Base, TimestampMixin):
    """Configuración operativa editable (mantenimiento) — fuente de verdad en DB.

    Bootstrap mínimo (DATABASE_URL / AUTH_SECRET) puede seguir en .env;
    correo, captura IA, estados auto, Stripe y dueños de plataforma viven aquí.
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="general", index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    help_text: Mapped[Optional[str]] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, default="string")  # string|bool|int|secret
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[Optional[str]] = mapped_column(String(128))


# --- Public sales channel (anonymous quote/checkout → org) ---


class PublicSalesChannel(Base, TimestampMixin):
    """Public commercial channel bound to one Organization (multi-tenant)."""

    __tablename__ = "public_sales_channels"
    __table_args__ = (UniqueConstraint("slug", name="uq_public_sales_channel_slug"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_code: Mapped[str] = mapped_column(String(40), nullable=False, default="VIAJE")
    product_label: Mapped[str] = mapped_column(String(200), nullable=False, default="Seguro de viaje")
    origin_default: Mapped[Optional[str]] = mapped_column(String(120))
    origin_fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_producer_profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    lead_source_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("crm_lead_sources.id"), nullable=True, index=True
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    branding_json: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class PublicProductPlan(Base, TimestampMixin):
    """Configurable plan offered on a public channel (not SaaS plan)."""

    __tablename__ = "public_product_plans"
    __table_args__ = (
        UniqueConstraint("channel_id", "code", name="uq_public_product_plan_channel_code"),
        Index("ix_public_product_plans_channel", "channel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    channel_id: Mapped[str] = mapped_column(ForeignKey("public_sales_channels.id"), index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    coverages_json: Mapped[Optional[str]] = mapped_column(Text)
    limits_json: Mapped[Optional[str]] = mapped_column(Text)
    highlight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PublicPlanRate(Base, TimestampMixin):
    """DEV/catalog rate row — replace with real tariff source when approved."""

    __tablename__ = "public_plan_rates"
    __table_args__ = (Index("ix_public_plan_rates_plan_region", "plan_id", "destination_region"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(ForeignKey("public_product_plans.id"), index=True)
    destination_region: Mapped[str] = mapped_column(String(40), nullable=False)
    age_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    age_max: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    amount_per_passenger_per_day: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(String(200))


class PublicQuote(Base, TimestampMixin):
    """Anonymous public quote session — system of record under channel.organization_id."""

    __tablename__ = "public_quotes"
    __table_args__ = (
        UniqueConstraint("public_token", name="uq_public_quote_token"),
        Index("ix_public_quotes_channel_status", "channel_id", "status"),
        Index("ix_public_quotes_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    public_token: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey("public_sales_channels.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="STARTED")
    origin: Mapped[Optional[str]] = mapped_column(String(120))
    destination: Mapped[Optional[str]] = mapped_column(String(200))
    destination_region: Mapped[Optional[str]] = mapped_column(String(40))
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    days: Mapped[Optional[int]] = mapped_column(Integer)
    passenger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ages_json: Mapped[Optional[str]] = mapped_column(Text)
    quoted_plans_json: Mapped[Optional[str]] = mapped_column(Text)
    selected_plan_code: Mapped[Optional[str]] = mapped_column(String(40))
    selected_plan_snapshot_json: Mapped[Optional[str]] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    selected_premium: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    crm_prospect_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("crm_prospects.id"), nullable=True, index=True
    )
    crm_opportunity_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("crm_opportunities.id"), nullable=True, index=True
    )
    # ESB cartera — filled after trusted PAID (landing is not ESB; ESB is SoR)
    party_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("parties.id"), nullable=True, index=True
    )
    policy_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("policies.id"), nullable=True, index=True
    )
    checkout_ref: Mapped[Optional[str]] = mapped_column(String(120))
    payment_status: Mapped[Optional[str]] = mapped_column(String(32))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    quoted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    selected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PublicQuoteTraveler(Base, TimestampMixin):
    __tablename__ = "public_quote_travelers"
    __table_args__ = (
        UniqueConstraint("quote_id", "seq", name="uq_public_quote_traveler_seq"),
        Index("ix_public_quote_travelers_quote", "quote_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(ForeignKey("public_quotes.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_name: Mapped[Optional[str]] = mapped_column(String(120))
    last_name: Mapped[Optional[str]] = mapped_column(String(120))
    birth_date: Mapped[Optional[date]] = mapped_column(Date)
    age: Mapped[Optional[int]] = mapped_column(Integer)
    identification_number: Mapped[Optional[str]] = mapped_column(String(64))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    is_pep: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PublicQuoteBeneficiary(Base, TimestampMixin):
    __tablename__ = "public_quote_beneficiaries"
    __table_args__ = (
        UniqueConstraint("traveler_id", "seq", name="uq_public_quote_beneficiary_seq"),
        Index("ix_public_quote_beneficiaries_traveler", "traveler_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    traveler_id: Mapped[str] = mapped_column(ForeignKey("public_quote_travelers.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    relationship: Mapped[Optional[str]] = mapped_column(String(80))
    identification_number: Mapped[Optional[str]] = mapped_column(String(64))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    share_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))


class PublicQuoteEmergencyContact(Base, TimestampMixin):
    __tablename__ = "public_quote_emergency_contacts"
    __table_args__ = (UniqueConstraint("quote_id", name="uq_public_quote_emergency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(ForeignKey("public_quotes.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(200))


class PublicPaymentAttempt(Base, TimestampMixin):
    """Pre-policy payment attempt for a public quote (provider-agnostic)."""

    __tablename__ = "public_payment_attempts"
    __table_args__ = (
        Index("ix_public_payment_attempts_quote", "quote_id"),
        Index("ix_public_payment_attempts_provider_ref", "provider_ref"),
        UniqueConstraint("idempotency_key", name="uq_public_payment_attempt_idem"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(ForeignKey("public_quotes.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey("public_sales_channels.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="SANDBOX")
    provider_ref: Mapped[Optional[str]] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    redirect_url: Mapped[Optional[str]] = mapped_column(Text)
    raw_event_json: Mapped[Optional[str]] = mapped_column(Text)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[Optional[str]] = mapped_column(String(240))
