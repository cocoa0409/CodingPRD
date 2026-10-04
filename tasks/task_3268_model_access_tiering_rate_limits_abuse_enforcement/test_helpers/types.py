"""Domain types: entity TypedDicts, status enums, role enum.

Primary resources carry id + created_at + updated_at + version.
Append-only resources carry ONLY id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class OrganizationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class OrganizationTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"
    ENTERPRISE = "ENTERPRISE"


class PaymentKind(str, Enum):
    PREPAID_TOPUP = "PREPAID_TOPUP"
    INVOICE_SETTLEMENT = "INVOICE_SETTLEMENT"
    REFUND = "REFUND"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"


class ModelVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    GATED = "GATED"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    SUNSET = "SUNSET"


class CapabilityClass(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    FRONTIER = "FRONTIER"


class SafetyEvaluationStatus(str, Enum):
    OPEN = "OPEN"
    PASSED = "PASSED"
    FAILED = "FAILED"


class EnterpriseAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class QueuedRequestStatus(str, Enum):
    QUEUED = "QUEUED"
    ADMITTED = "ADMITTED"
    EXPIRED = "EXPIRED"
    DROPPED = "DROPPED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class InvoiceLineKind(str, Enum):
    INPUT_TOKENS = "INPUT_TOKENS"
    OUTPUT_TOKENS = "OUTPUT_TOKENS"
    CACHED_TOKENS = "CACHED_TOKENS"


class AbuseCaseSource(str, Enum):
    AUTOMATED = "AUTOMATED"
    MANUAL = "MANUAL"


class AbuseCaseSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AbuseCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACTIONED = "ACTIONED"
    REINSTATED = "REINSTATED"


class AbuseActionType(str, Enum):
    WARN = "WARN"
    THROTTLE = "THROTTLE"
    RESTRICT = "RESTRICT"
    SUSPEND = "SUSPEND"
    TERMINATE = "TERMINATE"


class AppealStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ORGANIZATION_ADMIN = "OrganizationAdmin"
    BILLING_CONTACT = "BillingContact"
    TRUST_ANALYST = "TrustAnalyst"
    TRUST_LEAD = "TrustLead"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Organization(TypedDict, total=False):
    id: str
    legal_name: str
    tier: str
    status: str
    lifetime_spend_cents: int
    qualifying_payment_count: int
    pinned_model_version_id: Optional[str]
    enterprise_agreement_id: Optional[str]
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class PaymentEvent(TypedDict, total=False):
    # Append-only: only id + created_at are system-managed.
    id: str
    created_at: str
    organization_id: str
    kind: str
    amount_cents: int
    status: str


class UsageRecord(TypedDict, total=False):
    # Append-only: only id + created_at are system-managed.
    id: str
    created_at: str
    organization_id: str
    model_version_id: str
    minute_window_start: str
    requests: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    batch: bool


class ModelVersion(TypedDict, total=False):
    id: str
    model_slug: str
    version_tag: str
    status: str
    deprecation_announced_at: Optional[str]
    sunset_at: Optional[str]
    pricing: dict
    safety_evaluation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyEvaluation(TypedDict, total=False):
    id: str
    model_version_id: str
    capability_class: str
    status: str
    score: Optional[float]
    verdict_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnterpriseAgreement(TypedDict, total=False):
    id: str
    organization_id: str
    status: str
    committed_tpm: int
    dedicated_capacity_pct: int
    effective_at: str
    expires_at: str
    price_override: Optional[dict]
    created_at: str
    updated_at: str
    version: int


class RateLimitWindow(TypedDict, total=False):
    # Append-only counters snapshot: only id + created_at are system-managed.
    id: str
    created_at: str
    organization_id: str
    model_version_id: str
    window_start: str
    requests_used: int
    tokens_used: int
    burst_credits_used: int


class QueuedRequest(TypedDict, total=False):
    id: str
    organization_id: str
    model_version_id: str
    requests_cost: int
    tokens_cost: int
    status: str
    enqueued_at: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    organization_id: str
    period_start: str
    period_end: str
    status: str
    subtotal_cents: int
    batch_discount_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    # Append-only: only id + created_at are system-managed.
    id: str
    created_at: str
    invoice_id: str
    model_version_id: str
    kind: str
    quantity: int
    rate_per_mtok_cents: int
    batch: bool
    amount_cents: Optional[int]


class AbuseCase(TypedDict, total=False):
    id: str
    organization_id: str
    source: str
    classifier_confidence: Optional[float]
    status: str
    severity: str
    assigned_analyst_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbuseAction(TypedDict, total=False):
    # Append-only: only id + created_at are system-managed.
    id: str
    created_at: str
    abuse_case_id: str
    action_type: str
    issued_by: str
    revoked_at: Optional[str]


class Appeal(TypedDict, total=False):
    id: str
    abuse_case_id: str
    submitted_by: str
    status: str
    resolved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int
