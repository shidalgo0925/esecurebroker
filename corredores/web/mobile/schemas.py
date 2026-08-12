"""Pydantic request/response models — Mobile API v1 (OpenAPI)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., description="Email or piloto username")
    password: str


class SelectOrganizationRequest(BaseModel):
    organization_id: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_at: int = Field(..., description="Access token UNIX expiry")
    organization_id: str | None = None
    requires_organization_selection: bool = False
    organizations: list[dict[str, Any]] = Field(default_factory=list)


class IdentityOut(BaseModel):
    subject_id: str
    username: str
    display_name: str | None = None


class OrganizationOut(BaseModel):
    id: str
    name: str
    active: bool


class MembershipOut(BaseModel):
    id: str | None
    role_code: str
    active: bool = True


class SessionOut(BaseModel):
    api_version: str = "v1"
    scope: Literal["ORGANIZATION", "ASSIGNED_PORTFOLIO", "PLATFORM"]
    organization_selected: bool
    access_expires_at: int
    producer_profile_id: str | None = None


class MeResponse(BaseModel):
    identity: IdentityOut
    organization: OrganizationOut | None
    membership: MembershipOut | None
    role: str
    scope: Literal["ORGANIZATION", "ASSIGNED_PORTFOLIO", "PLATFORM"]
    permissions: list[str]
    entitlements: dict[str, Any]
    session: SessionOut
    organizations_available: list[dict[str, Any]] = Field(default_factory=list)
    producer_profile_id: str | None = None


class MoneyCardOut(BaseModel):
    key: str
    amount_label: str
    title: str
    subtitle: str
    href: str | None = None


class AttentionCardOut(BaseModel):
    kind: str
    urgency: str
    title: str
    subject: str
    lines: list[str]
    stamp: str
    party_id: str | None = None
    policy_id: str | None = None
    claim_id: str | None = None
    renewal_id: str | None = None


class SystemWorkOut(BaseModel):
    text: str
    amount_label: str | None = None


class OpportunityOut(BaseModel):
    text: str
    href: str | None = None


class TodayResponse(BaseModel):
    as_of: str
    date_label: str
    greeting: str
    attention_count: int
    money: list[MoneyCardOut]
    attention: list[AttentionCardOut]
    system_work: list[SystemWorkOut]
    opportunities: list[OpportunityOut]
    auto_cuotas_managed: int = 0
    reminders_sent_today: int = 0


class CustomerListItem(BaseModel):
    id: str
    name: str
    national_id: str | None = None
    party_type: str
    phone: str | None = None
    email: str | None = None
    district: str | None = None
    policies_count: int = 0


class CustomerListResponse(BaseModel):
    items: list[CustomerListItem]
    count: int
    q: str | None = None
    party_type: str | None = None
    search_fields: list[str] = Field(
        default_factory=lambda: [
            "first_name",
            "last_name",
            "legal_name",
            "national_id",
            "phone",
            "email",
        ],
        description="v1 supported search fields (no plate/policy on customers)",
    )


class CustomerDetailResponse(BaseModel):
    id: str
    name: str
    party_type: str
    national_id: str | None = None
    phone: str | None = None
    email: str | None = None
    district: str | None = None
    address: str | None = None
    birth_date: str | None = None


class Customer360Response(BaseModel):
    customer: CustomerDetailResponse
    contact: dict[str, Any]
    policies: list[dict[str, Any]]
    vehicles: list[dict[str, Any]]
    renewals: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    promises: dict[str, int]
    balance: dict[str, Any]
    gaps: list[dict[str, Any]]
    roles: list[str]
    submissions: list[dict[str, Any]] = Field(default_factory=list)


class PolicyListItem(BaseModel):
    id: str
    policy_number: str
    status: str
    client_party_id: str | None = None
    client_name: str | None = None
    carrier_name: str | None = None
    line_code: str | None = None
    premium: str | None = None
    effective_date: str | None = None
    expiration_date: str | None = None


class PolicyListResponse(BaseModel):
    items: list[PolicyListItem]
    count: int
    q: str | None = None


class PolicyDetailResponse(BaseModel):
    id: str
    policy_number: str
    status: str
    client_party_id: str | None
    client_name: str | None
    client_national_id: str | None = None
    carrier_id: str | None = None
    carrier_name: str | None = None
    insurance_line_id: str | None = None
    line_code: str | None = None
    net_premium: str | None = None
    gross_premium: str | None = None
    annual_premium: str | None = None
    effective_date: str | None = None
    expiration_date: str | None = None
    vehicle: dict[str, Any] | None = None


# --- F5A activities / documents ---

ActivityType = Literal["NOTE", "CALL", "EMAIL", "WHATSAPP", "VISIT", "OTHER"]


class ActivityCreateRequest(BaseModel):
    customer_id: str = Field(..., description="Required context party")
    policy_id: str | None = None
    activity_type: ActivityType = "NOTE"
    note: str = Field(..., min_length=1, max_length=4000)
    client_activity_id: str | None = Field(
        default=None, max_length=128, description="Idempotency key from device"
    )


class ActivityOut(BaseModel):
    id: str
    customer_id: str | None
    policy_id: str | None
    activity_type: str
    note: str
    actor_id: str | None
    client_activity_id: str | None = None
    created_at: str | None
    status: Literal["SYNCED"] = "SYNCED"
    idempotency: Literal["created", "replayed"] | None = None


class ActivityListResponse(BaseModel):
    items: list[ActivityOut]
    count: int


class DocumentOut(BaseModel):
    document_id: str
    status: Literal["SYNCED"] = "SYNCED"
    created_at: str | None
    title: str
    document_type: str
    original_filename: str
    content_type: str
    size_bytes: int
    context: dict[str, Any]
    idempotency: Literal["created", "replayed"] | None = None


class DocumentListItem(BaseModel):
    document_id: str
    title: str
    document_type: str
    original_filename: str
    content_type: str
    size_bytes: int
    customer_id: str | None
    policy_id: str | None
    created_at: str | None
    status: Literal["SYNCED"] = "SYNCED"


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    count: int
    customer_id: str
