"""Domain types: entity TypedDicts, status enums, role enum (PRD §2/§3)."""
from enum import Enum
from typing import Optional, TypedDict


class SourceType(str, Enum):
    COURT = "COURT"
    LEGISLATURE = "LEGISLATURE"
    AGENCY = "AGENCY"


class DocumentType(str, Enum):
    CASE = "CASE"
    STATUTE = "STATUTE"
    REGULATION = "REGULATION"


class IngestionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PUBLISHED = "PUBLISHED"


class VisibilityStatus(str, Enum):
    PUBLIC = "PUBLIC"
    SEALED = "SEALED"
    REMOVED = "REMOVED"


class CitatorSignal(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class Treatment(str, Enum):
    OVERRULED = "OVERRULED"
    CRITICIZED = "CRITICIZED"
    QUESTIONED = "QUESTIONED"
    DISTINGUISHED = "DISTINGUISHED"
    FOLLOWED = "FOLLOWED"
    CITED_NEUTRALLY = "CITED_NEUTRALLY"


class Depth(str, Enum):
    EXAMINED = "EXAMINED"
    DISCUSSED = "DISCUSSED"
    CITED = "CITED"
    MENTIONED = "MENTIONED"


class ReferenceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TopicCode(str, Enum):
    LITIGATION = "LITIGATION"
    CORPORATE = "CORPORATE"
    TAX = "TAX"
    IP = "IP"
    CRIMINAL = "CRIMINAL"
    FAMILY = "FAMILY"


class HeadnoteStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"


class PracticeArea(str, Enum):
    LITIGATION = "LITIGATION"
    CORPORATE = "CORPORATE"
    TAX = "TAX"
    IP = "IP"
    CRIMINAL = "CRIMINAL"
    FAMILY = "FAMILY"
    ALL = "ALL"


class JurisdictionScope(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    NATIONAL = "NATIONAL"


class FirmSizeTier(str, Enum):
    SOLO = "SOLO"
    SMALL = "SMALL"
    MID = "MID"
    LARGE = "LARGE"


class BillingModel(str, Enum):
    FLAT_RATE = "FLAT_RATE"
    TRANSACTIONAL = "TRANSACTIONAL"


class ScopeEnforcement(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class AccountType(str, Enum):
    LAW_FIRM = "LAW_FIRM"
    GOVERNMENT = "GOVERNMENT"
    CORPORATE = "CORPORATE"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class SuspensionReason(str, Enum):
    MANUAL = "MANUAL"
    INVOICE_OVERDUE = "INVOICE_OVERDUE"


class SeatStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"


class UsageEventType(str, Enum):
    SEARCH = "SEARCH"
    DOC_VIEW = "DOC_VIEW"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    VOID = "VOID"


class RoyaltyBasis(str, Enum):
    PER_VIEW = "PER_VIEW"
    REVENUE_SHARE = "REVENUE_SHARE"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class RemovalScope(str, Enum):
    SEAL = "SEAL"
    REMOVE = "REMOVE"


class RemovalOrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CONTENT_INGESTER = "ContentIngester"
    CITATOR_ANALYST = "CitatorAnalyst"
    ATTORNEY_EDITOR = "AttorneyEditor"
    LICENSING_MANAGER = "LicensingManager"
    FIRM_ADMIN = "FirmAdmin"
    RESEARCHER = "Researcher"
    BILLING_ADMIN = "BillingAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Entity TypedDicts (common_fields: true — id/created_at/updated_at/version) ---


class PrimaryDocument(TypedDict, total=False):
    id: str
    source_type: str
    jurisdiction_code: str
    document_type: str
    title: str
    raw_citation_string: str
    normalized_citation: Optional[str]
    decision_date: str
    ingestion_status: str
    visibility_status: str
    citator_score: int
    citator_signal: str
    editorial_override_signal: Optional[str]
    editorial_override_rationale: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CitingReference(TypedDict, total=False):
    id: str
    citing_document_id: str
    cited_document_id: str
    treatment: str
    depth: str
    status: str
    deactivated_by_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Headnote(TypedDict, total=False):
    id: str
    document_id: str
    author_editor_id: str
    reviewer_editor_id: Optional[str]
    topic_code: str
    headnote_text: str
    synopsis_text: str
    review_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionPlan(TypedDict, total=False):
    id: str
    name: str
    practice_area: str
    jurisdiction_scope: str
    firm_size_tier: str
    billing_model: str
    monthly_fee_cents: Optional[int]
    included_searches: Optional[int]
    included_doc_views: Optional[int]
    overage_search_fee_cents: Optional[int]
    overage_doc_view_fee_cents: Optional[int]
    volume_discount_pct: Optional[float]
    discount_threshold_overage_units: Optional[int]
    per_search_fee_cents: Optional[int]
    per_doc_view_fee_cents: Optional[int]
    scope_enforcement: str
    government_only: bool
    cost_recovery_allowed: bool
    bulk_hourly_limit: int
    bulk_daily_limit: int
    created_at: str
    updated_at: str
    version: int


class SubscriberAccount(TypedDict, total=False):
    id: str
    org_name: str
    account_type: str
    cost_recovery_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    account_id: str
    plan_id: str
    period_start: str
    period_end: str
    seats_total: int
    seats_used: int
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubscriberUser(TypedDict, total=False):
    id: str
    account_id: str
    email: str
    full_name: str
    seat_status: str
    seat_subscription_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    subscription_id: str
    period_start: str
    period_end: str
    billing_model: str
    base_fee_cents: int
    search_count: int
    doc_view_count: int
    overage_search_units: int
    overage_view_units: int
    overage_fee_cents: int
    total_cents: int
    cost_recovery_allocation: list
    status: str
    issued_at: Optional[str]
    due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict, total=False):
    id: str
    work_title: str
    author_name: str
    practice_area: str
    royalty_basis: str
    per_view_fee_cents: Optional[int]
    revenue_share_bps: Optional[int]
    exclusive: bool
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RemovalOrder(TypedDict, total=False):
    id: str
    document_id: str
    scope: str
    effective_from: str
    effective_until: str
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger entries (common_fields: false — ONLY id + created_at) ---


class UsageEvent(TypedDict, total=False):
    id: str
    subscription_id: str
    user_id: str
    event_type: str
    practice_area_tag: str
    license_agreement_id: Optional[str]
    matter_code: Optional[str]
    in_scope: bool
    occurred_at: str
    created_at: str


class RoyaltyStatement(TypedDict, total=False):
    id: str
    license_agreement_id: str
    period_start: str
    period_end: str
    view_count: int
    revenue_base_cents: int
    royalty_amount_cents: int
    created_at: str
