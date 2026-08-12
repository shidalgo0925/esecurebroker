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
    channel: Mapped[str] = mapped_column(String(32), default="NOTE")  # NOTE|CALL|EMAIL|WHATSAPP|OTHER
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(String(64))
    data_source: Mapped[str] = mapped_column(String(32), default="MANUAL")


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
    """Subject ↔ Organization (ADR-007). Piloto uses actor_id; EN1 will map subjects later.

    role_code (ADR-008): OWNER|ADMIN|BROKER|PRODUCER|COLLECTIONS|PLATFORM.
    F1 recognizes codes only — RBAC enforcement is F2+. BROKER = legacy/transitional.
    """

    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("subject_id", "organization_id", name="uq_org_membership_subject_org"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Optional display for piloto; EN1 will own profile later
    display_name: Mapped[Optional[str]] = mapped_column(String(200))
    role_code: Mapped[str] = mapped_column(String(64), nullable=False, default="BROKER")
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    external_en1_membership_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True)


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
