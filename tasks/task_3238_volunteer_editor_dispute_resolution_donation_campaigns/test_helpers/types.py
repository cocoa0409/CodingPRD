"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"


class TopicArea(str, Enum):
    GENERAL = "GENERAL"
    POLITICS = "POLITICS"
    HEALTH = "HEALTH"
    BIOGRAPHY = "BIOGRAPHY"
    HISTORY = "HISTORY"


class ProtectionLevel(str, Enum):
    NONE = "NONE"
    SEMI = "SEMI"
    FULL = "FULL"


class DisputeLevel(str, Enum):
    NONE = "NONE"
    TALK = "TALK"
    NOTICE = "NOTICE"
    ARB = "ARB"


class RevisionStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVERTED = "REVERTED"
    FLAGGED = "FLAGGED"


class DisputeType(str, Enum):
    CONTENT = "CONTENT"
    CONDUCT = "CONDUCT"
    SOURCING = "SOURCING"
    NOTABILITY = "NOTABILITY"


class DisputeCaseLevel(str, Enum):
    TALK = "TALK"
    NOTICE = "NOTICE"
    ARBITRATION = "ARBITRATION"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ProtectionRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class VandalismReportType(str, Enum):
    VANDALISM = "VANDALISM"
    SPAM = "SPAM"
    BLP_VIOLATION = "BLP_VIOLATION"
    COPYVIO = "COPYVIO"


class VandalismReportStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BannerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class DonationStatus(str, Enum):
    PLEDGED = "PLEDGED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class GrantProgramStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class GrantApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class LegalRequestType(str, Enum):
    TAKEDOWN = "TAKEDOWN"
    USER_INFO = "USER_INFO"
    SUBPOENA = "SUBPOENA"
    COURT_ORDER = "COURT_ORDER"


class LegalRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    COMPLIED = "COMPLIED"
    REJECTED = "REJECTED"
    PARTIALLY_COMPLIED = "PARTIALLY_COMPLIED"


class TransparencyReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    VOLUNTEER_EDITOR = "VolunteerEditor"
    ADMINISTRATOR = "Administrator"
    FUNDRAISING_MANAGER = "FundraisingManager"
    PAYMENT_PROCESSOR = "PaymentProcessor"
    GRANT_ADMINISTRATOR = "GrantAdministrator"
    GRANT_REVIEWER = "GrantReviewer"
    LEGAL_COUNSEL = "LegalCounsel"
    PLATFORM_ADMIN = "PlatformAdmin"


class VolunteerEditor(TypedDict, total=False):
    id: str
    username: str
    email: str
    account_status: str
    rollback_eligible: bool
    coi_disclosure_required: bool
    coi_disclosed: bool
    edit_count: int
    created_at: str
    updated_at: str
    version: int


class WikiPage(TypedDict, total=False):
    id: str
    title: str
    topic_area: str
    protection_level: str
    current_revision_id: Optional[str]
    content_score: float
    dispute_level: str
    created_at: str
    updated_at: str
    version: int


class Revision(TypedDict, total=False):
    id: str
    page_id: str
    editor_id: str
    content_text: str
    summary: str
    status: str
    vandalism_score: float
    source_quality_score: float
    neutrality_score: float
    created_at: str
    updated_at: str


class DisputeCase(TypedDict, total=False):
    id: str
    page_id: str
    initiator_id: str
    respondent_id: str
    subject_revision_id: str
    dispute_type: str
    level: str
    status: str
    opened_at: str
    escalated_at: Optional[str]
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProtectionRequest(TypedDict, total=False):
    id: str
    page_id: str
    requested_by_id: str
    requested_level: str
    reason: str
    status: str
    expires_at: Optional[str]
    reviewed_by_id: Optional[str]
    created_at: str
    updated_at: str


class VandalismReport(TypedDict, total=False):
    id: str
    revision_id: str
    reporter_id: str
    report_type: str
    status: str
    auto_flagged: bool
    rollback_applied: bool
    created_at: str
    updated_at: str


class DonationCampaign(TypedDict, total=False):
    id: str
    name: str
    start_at: str
    end_at: str
    target_amount_cents: int
    status: str
    raised_cents: int
    created_at: str
    updated_at: str
    version: int


class CampaignBanner(TypedDict, total=False):
    id: str
    campaign_id: str
    message_variant: str
    geo_target: str
    frequency_cap: int
    priority_weight: int
    status: str
    impression_count: int
    click_count: int
    conversion_count: int
    conversion_rate_bp: int
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict, total=False):
    id: str
    campaign_id: str
    banner_id: str
    donor_email_hash: str
    amount_cents: int
    currency: str
    status: str
    processed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantProgram(TypedDict, total=False):
    id: str
    name: str
    fiscal_year: int
    budget_cents: int
    allocated_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantApplication(TypedDict, total=False):
    id: str
    program_id: str
    applicant_id: str
    project_title: str
    requested_cents: int
    status: str
    review_score: float
    awarded_cents: int
    created_at: str
    updated_at: str
    version: int


class LegalRequest(TypedDict, total=False):
    id: str
    request_type: str
    target_page_id: Optional[str]
    target_user_id: Optional[str]
    requesting_party: str
    received_at: str
    status: str
    transparency_report_id: Optional[str]
    created_at: str
    updated_at: str


class TransparencyReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    total_requests: int
    complied_count: int
    rejected_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpressionEvent(TypedDict, total=False):
    id: str
    banner_id: str
    viewer_key: str
    country_code: str
    served_at: str
    day_bucket: str
    clicked: bool
    created_at: str
    updated_at: str
