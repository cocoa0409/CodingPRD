"""Domain types: entity TypedDicts, status enums, role enum.

Every primary resource carries the common fields id, created_at, updated_at,
version (PRD section "Common Resource Properties").
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    CONTRACT_ADMIN = "ContractAdmin"
    SEAT_ADMIN = "SeatAdmin"
    RECRUITER_USER = "RecruiterUser"
    ATS_SERVICE = "AtsService"
    AUDITOR = "Auditor"


class ProductTier(str, Enum):
    RECRUITER_LITE = "RECRUITER_LITE"
    RECRUITER_PRO = "RECRUITER_PRO"
    RECRUITER_CORP = "RECRUITER_CORP"


class ContractStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXPIRED = "EXPIRED"


class SeatStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class RecruiterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class LedgerStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    THROTTLED = "THROTTLED"
    CLOSED = "CLOSED"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class ResponseStatus(str, Enum):
    AWAITING = "AWAITING"
    RESPONDED = "RESPONDED"
    NEGATIVE_RESPONSE = "NEGATIVE_RESPONSE"
    REPORTED_AS_SPAM = "REPORTED_AS_SPAM"
    EXPIRED = "EXPIRED"


class PrivacySetting(str, Enum):
    PUBLIC = "PUBLIC"
    CONNECTIONS_ONLY = "CONNECTIONS_ONLY"
    PRIVATE = "PRIVATE"


class OpenToWorkVisibility(str, Enum):
    ALL_MEMBERS = "ALL_MEMBERS"
    RECRUITERS_ONLY = "RECRUITERS_ONLY"
    NONE = "NONE"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ON_HOLD = "ON_HOLD"
    CLOSED = "CLOSED"


class PacingMode(str, Enum):
    EVEN = "EVEN"
    FRONT_LOADED = "FRONT_LOADED"


class PostingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class SlotStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class AtsVendor(str, Enum):
    GREENHOUSE = "GREENHOUSE"
    LEVER = "LEVER"
    WORKDAY = "WORKDAY"
    ICIMS = "ICIMS"


class IntegrationStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    CONNECTED = "CONNECTED"
    SYNC_ERROR = "SYNC_ERROR"
    DISABLED = "DISABLED"


class AtsEventType(str, Enum):
    APPLICATION_FORWARDED = "APPLICATION_FORWARDED"
    STAGE_CHANGED = "STAGE_CHANGED"
    HIRED = "HIRED"
    DISQUALIFIED = "DISQUALIFIED"


class SyncStatus(str, Enum):
    QUEUED = "QUEUED"
    WRITTEN = "WRITTEN"
    DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"
    FAILED = "FAILED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    PUBLISHED = "PUBLISHED"
    SUPPRESSED = "SUPPRESSED"


class RenewalEventKind(str, Enum):
    TRUE_UP = "TRUE_UP"
    RENEWAL = "RENEWAL"
    SUSPENSION = "SUSPENSION"


class RenewalEventStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class ResponseKind(str, Enum):
    RESPONDED = "RESPONDED"
    NEGATIVE_RESPONSE = "NEGATIVE_RESPONSE"
    REPORTED_AS_SPAM = "REPORTED_AS_SPAM"


class RecruiterContract(TypedDict, total=False):
    id: str
    contract_number: str
    product_tier: str
    seat_cap: int
    seats_purchased: int
    seats_assigned: int
    monthly_credit_per_seat: int
    monthly_search_quota_per_seat: int
    search_result_page_cap: int
    current_period_start: str
    current_period_end: str
    period_index: int
    contract_status: str
    true_up_allowed: bool
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict, total=False):
    id: str
    contract_id: str
    seat_label: str
    seat_status: str
    assigned_recruiter_id: Optional[str]
    assignment_started_at: Optional[str]
    assignment_audit_count: int
    last_period_credit_refresh: int
    created_at: str
    updated_at: str
    version: int


class Recruiter(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    manager_recruiter_id: Optional[str]
    recruiter_status: str
    home_contract_id: str
    active_seat_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuotaLedger(TypedDict, total=False):
    id: str
    seat_id: str
    period_index: int
    search_quota_total: int
    searches_used: int
    searches_remaining: int
    ledger_status: str
    created_at: str
    updated_at: str
    version: int


class MessageCreditPool(TypedDict, total=False):
    id: str
    seat_id: str
    period_index: int
    credits_granted: int
    credits_used: int
    credits_returned: int
    credits_available: int
    spam_strike_count: int
    pool_status: str
    created_at: str
    updated_at: str
    version: int


class Message(TypedDict, total=False):
    id: str
    seat_id: str
    candidate_id: str
    project_id: str
    job_posting_id: Optional[str]
    body: str
    delivery_status: str
    response_status: str
    credit_consumed: int
    credit_returned_flag: bool
    created_at: str
    updated_at: str
    version: int


class CandidateProfile(TypedDict, total=False):
    id: str
    member_id: str
    full_name: str
    headline: str
    privacy_setting: str
    open_to_work: bool
    open_to_work_visibility: str
    years_experience: int
    current_title: str
    created_at: str
    updated_at: str
    version: int


class SearchProject(TypedDict, total=False):
    id: str
    contract_id: str
    owner_seat_id: str
    name: str
    project_status: str
    pinned_candidate_ids: List[str]
    message_count: int
    created_at: str
    updated_at: str
    version: int


class JobPosting(TypedDict, total=False):
    id: str
    contract_id: str
    created_by_seat_id: str
    title: str
    budget_cents: int
    daily_cap_cents: int
    pacing_mode: str
    start_at: str
    end_at: str
    spent_cents: int
    posting_status: str
    created_at: str
    updated_at: str
    version: int


class PromotedSlot(TypedDict, total=False):
    id: str
    job_posting_id: str
    slot_date: str
    reserved_cents: int
    slot_status: str
    created_at: str
    updated_at: str
    version: int


class AtsIntegration(TypedDict, total=False):
    id: str
    contract_id: str
    vendor: str
    external_tenant_id: str
    write_back_enabled: bool
    integration_status: str
    created_at: str
    updated_at: str
    version: int


class AtsSyncRecord(TypedDict, total=False):
    id: str
    ats_integration_id: str
    candidate_id: str
    external_candidate_ref: str
    event_type: str
    payload_fingerprint: str
    sync_status: str
    created_at: str
    updated_at: str
    version: int


class TalentInsightReport(TypedDict, total=False):
    id: str
    contract_id: str
    report_name: str
    filter_spec: Any
    matched_count: int
    aggregation_floor: int
    report_status: str
    created_at: str
    updated_at: str
    version: int


class RenewalEvent(TypedDict, total=False):
    id: str
    contract_id: str
    event_kind: str
    seats_delta: Optional[int]
    requested_by: str
    event_status: str
    proration_credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
