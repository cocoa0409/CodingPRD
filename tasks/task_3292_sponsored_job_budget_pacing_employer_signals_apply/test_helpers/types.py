"""Domain types for the Sponsored Job Pacing API.

Entity TypedDicts, lifecycle status enums and the role enum, drawn from the
PRD's entity model and state machines. Envelope types are not repeated here;
they come from the shared testing framework.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    TRUST_REVIEWER = "TrustReviewer"
    EMPLOYER = "Employer"
    JOB_SEEKER = "JobSeeker"


# ─── Status enums ─────────────────────────────────────

class EmployerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    FROZEN = "FROZEN"


class AtsProvider(str, Enum):
    WORKDAY = "WORKDAY"
    GREENHOUSE = "GREENHOUSE"
    LEVER = "LEVER"
    TALEO = "TALEO"
    NONE = "NONE"


class SeekerStatus(str, Enum):
    ACTIVE = "ACTIVE"


class PricingModel(str, Enum):
    CPC = "CPC"
    CPA = "CPA"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PACING_HOLD = "PACING_HOLD"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class SponsoredJobStatus(str, Enum):
    DRAFT = "DRAFT"
    ELIGIBLE = "ELIGIBLE"
    PAUSED = "PAUSED"
    BUDGET_HOLD = "BUDGET_HOLD"


class PostingState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    EXPIRED = "EXPIRED"


class ApplyMode(str, Enum):
    HOSTED = "HOSTED"
    ATS_REDIRECT = "ATS_REDIRECT"


class ApplicationStatus(str, Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    RESPONDED = "RESPONDED"
    CLOSED = "CLOSED"


class Disposition(str, Enum):
    NONE = "NONE"
    REVIEWED = "REVIEWED"
    INTERVIEW = "INTERVIEW"
    REJECTED = "REJECTED"
    HIRED = "HIRED"


RESPONDING_DISPOSITIONS = ["REVIEWED", "INTERVIEW", "REJECTED", "HIRED"]


class AssessmentQuestionKind(str, Enum):
    BOOLEAN = "BOOLEAN"
    SINGLE_CHOICE = "SINGLE_CHOICE"
    NUMERIC = "NUMERIC"


class AssessmentStatus(str, Enum):
    PUBLISHED = "PUBLISHED"


class ApplyEventKind(str, Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    INVALID_CLICK = "INVALID_CLICK"


class ApplyEventSource(str, Enum):
    HOSTED = "HOSTED"
    REDIRECT = "REDIRECT"
    PIXEL = "PIXEL"


class SponsorEventType(str, Enum):
    IMPRESSION = "IMPRESSION"
    CLICK = "CLICK"
    APPLICATION = "APPLICATION"


class SponsorEventStatus(str, Enum):
    RECORDED = "RECORDED"
    BILLED = "BILLED"
    REFUNDED = "REFUNDED"


class LedgerEntryType(str, Enum):
    HOLD = "HOLD"
    COMMIT = "COMMIT"
    RELEASE = "RELEASE"
    REFUND = "REFUND"


class PacingHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"


# ─── Entity TypedDicts ────────────────────────────────
# common_fields: true — carries id + created_at + updated_at + version

class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    domain: str
    ats_provider: str
    status: str
    quality_score: int
    response_rate_bps: int
    billing_status: str
    balance_cents: int
    last_invoice_at: Optional[str]
    suspended_at: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JobSeeker(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    location: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    employer_id: str
    name: str
    pricing_model: str
    daily_budget_cents: int
    total_budget_cents: int
    status: str
    spent_cents: int
    daily_spent_cents: int
    held_cents: int
    day_open_date: str
    created_at: str
    updated_at: str
    version: int


class SponsoredJob(TypedDict, total=False):
    id: str
    campaign_id: str
    job_posting_id: str
    cpc_bid_cents: int
    cpa_bid_cents: int
    scheduled_pacing_multiplier: float
    realized_pacing_multiplier: float
    status: str
    impressions: int
    clicks: int
    applications: int
    created_at: str
    updated_at: str
    version: int


class JobPosting(TypedDict, total=False):
    id: str
    employer_id: str
    title: str
    location: str
    description_text: str
    state: str
    current_freshness: str
    apply_mode: str
    apply_redirect_url: Optional[str]
    posted_at: str
    apply_started_count: int
    apply_completed_count: int
    dedupe_key: str
    external_posting_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JobPostingVersion(TypedDict, total=False):
    id: str
    job_posting_id: str
    content_hash: str
    external_posting_id: str
    ingested_at: str
    freshness: str
    title: str
    description_text: str
    apply_mode: str
    apply_redirect_url: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    job_posting_id: str
    questions: List[dict]
    pass_threshold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    job_posting_id: str
    job_seeker_id: str
    status: str
    started_at: str
    completed_at: Optional[str]
    disposition: str
    responded_at: Optional[str]
    assessment_id: Optional[str]
    assessment_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at

class ApplyEvent(TypedDict, total=False):
    id: str
    application_id: str
    kind: str
    source: str
    occurred_at: str
    created_at: str


class BudgetLedger(TypedDict, total=False):
    id: str
    campaign_id: str
    entry_type: str
    amount_cents: int
    sponsor_event_id: Optional[str]
    reference_code: str
    created_at: str


# common_fields: true

class JobAlertSubscription(TypedDict, total=False):
    id: str
    job_seeker_id: str
    keywords: str
    location: str
    status: str
    last_notified_at: Optional[str]
    notified_posting_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class SponsorEvent(TypedDict, total=False):
    id: str
    campaign_id: str
    sponsored_job_id: str
    event_type: str
    billable: bool
    cost_cents: int
    status: str
    occurred_at: str
    device_fingerprint: str
    ip_hash: str
    created_at: str
    updated_at: str
    version: int


class PacingHold(TypedDict, total=False):
    id: str
    sponsored_job_id: str
    campaign_id: str
    amount_cents: int
    status: str
    sponsor_event_id: Optional[str]
    created_at: str
    updated_at: str
    version: int