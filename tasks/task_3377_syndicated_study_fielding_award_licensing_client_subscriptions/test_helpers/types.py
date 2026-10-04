"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    STUDY_ADMIN = "StudyAdmin"
    METHODOLOGY_LEAD = "MethodologyLead"
    FIELD_OPS = "FieldOps"
    AWARDS_OFFICER = "AwardsOfficer"
    LICENSING_MANAGER = "LicensingManager"
    CLIENT_USER = "ClientUser"
    PRESS_USER = "PressUser"


class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    DESIGN_LOCKED = "DESIGN_LOCKED"
    FIELDING = "FIELDING"
    FIELDING_CLOSED = "FIELDING_CLOSED"
    SCORING = "SCORING"
    SCORED = "SCORED"
    AWARDS_SET = "AWARDS_SET"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class MethodologyStatus(str, Enum):
    DRAFT = "DRAFT"
    PINNED = "PINNED"
    SUPERSEDED = "SUPERSEDED"


class ChangeClass(str, Enum):
    FULL_COMPARABLE = "FULL_COMPARABLE"
    ADJUSTED = "ADJUSTED"
    BREAK = "BREAK"


class SourceType(str, Enum):
    PANEL = "PANEL"
    CUSTOMER_LIST = "CUSTOMER_LIST"


class FrameStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class QualityStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RejectReason(str, Enum):
    SPEEDER = "SPEEDER"
    STRAIGHTLINE = "STRAIGHTLINE"
    DUPLICATE = "DUPLICATE"


class BrandResultStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    AWARDED = "AWARDED"


class AwardStatus(str, Enum):
    EMBARGOED = "EMBARGOED"
    PUBLISHED = "PUBLISHED"


class LicenseTier(str, Enum):
    DIGITAL = "DIGITAL"
    NATIONAL = "NATIONAL"
    GLOBAL = "GLOBAL"


class LicenseStatus(str, Enum):
    QUOTED = "QUOTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class AuditSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class AuditResolution(str, Enum):
    CONFIRMED = "CONFIRMED"
    LICENSE_REVOKED_AUTO = "LICENSE_REVOKED_AUTO"


class SubscriptionTier(str, Enum):
    DIAGNOSTIC = "DIAGNOSTIC"
    BENCHMARK = "BENCHMARK"


class SubscriptionStatus(str, Enum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ClientType(str, Enum):
    BRAND = "BRAND"
    AGENCY = "AGENCY"


# --- Entity TypedDicts (common_fields: id, created_at, updated_at, version) ---


class Study(TypedDict, total=False):
    id: str
    code: str
    name: str
    industry_code: str
    cycle_year: int
    prior_study_id: Optional[str]
    min_sample_per_brand: int
    significance_alpha: float
    embargo_lift_at: str
    status: str
    active_methodology_id: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Brand(TypedDict, total=False):
    id: str
    name: str
    industry_code: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    name: str
    client_type: str
    country: str
    brand_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MethodologyVersion(TypedDict, total=False):
    id: str
    study_id: str
    change_class: str
    change_notes: Optional[str]
    min_duration_seconds: int
    straightline_min_items: int
    pooled_sd_1000: float
    z_value: float
    tie_epsilon: float
    version_no: int
    status: str
    pinned_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Factor(TypedDict, total=False):
    # Append-only factor rows: only id + created_at, no updated_at / version (PRD §2.4).
    id: str
    methodology_version_id: str
    code: str
    name: str
    weight_bp: int
    ordinal: int
    created_at: str


class SampleFrame(TypedDict, total=False):
    id: str
    study_id: str
    brand_id: str
    source_type: str
    target_completes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Response(TypedDict, total=False):
    id: str
    frame_id: str
    respondent_token: str
    duration_seconds: int
    item_count: int
    distinct_values: int
    factor_scores: list
    study_id: str
    brand_id: str
    submitted_at: str
    quality_status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BrandResult(TypedDict, total=False):
    id: str
    study_id: str
    brand_id: str
    provisional_accepted_n: int
    accepted_n: int
    provisional_index: Optional[int]
    final_index: Optional[int]
    eligible: Optional[bool]
    significance_group: Optional[int]
    rank_position: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    study_id: str
    brand_id: str
    rank_position: int
    significance_group: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    award_id: str
    client_id: str
    tier: str
    term_months: int
    markets_count: int
    fee_quote_cents: int
    fee_final_cents: Optional[int]
    status: str
    activated_at: Optional[str]
    expires_at: Optional[str]
    suspension_count: int
    created_at: str
    updated_at: str
    version: int


class UsageAudit(TypedDict, total=False):
    id: str
    license_id: str
    severity: str
    note: Optional[str]
    status: str
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    client_id: str
    study_id: str
    tier: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
