"""Domain types for the Developer Relations API Program: entity shapes, state enums, roles.

Every enum value here is quoted from the PRD's own vocabulary.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    DEVELOPER = "Developer"
    DEV_REL_MANAGER = "DevRelManager"
    PLATFORM_ADMIN = "PlatformAdmin"
    TRUST_AND_SAFETY_OFFICER = "TrustAndSafetyOfficer"
    PARTNER_SUPPORT_AGENT = "PartnerSupportAgent"
    ANONYMOUS = "Anonymous"


ALL_ROLES = [r.value for r in UserRole]


# ------------------------------------------------------------------ developer enums
class OnboardingState(str, Enum):
    REGISTERED = "REGISTERED"
    DOCS_ACKNOWLEDGED = "DOCS_ACKNOWLEDGED"
    SANDBOX_VALIDATED = "SANDBOX_VALIDATED"
    PRODUCTION_ACTIVE = "PRODUCTION_ACTIVE"


class Standing(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESTRICTED = "RESTRICTED"
    REVOKED = "REVOKED"


class DirectoryState(str, Enum):
    NOT_LISTED = "NOT_LISTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class CertificationLevel(str, Enum):
    NONE = "NONE"
    ASSOCIATE = "ASSOCIATE"
    PROFESSIONAL = "PROFESSIONAL"


class RegionCode(str, Enum):
    US = "US"
    EU = "EU"
    APAC = "APAC"


# -------------------------------------------------------------------- product enums
class DataSensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    PERSONAL = "PERSONAL"
    FINANCIAL = "FINANCIAL"


class VersionLifecycleState(str, Enum):
    PREVIEW = "PREVIEW"
    GENERAL_AVAILABILITY = "GENERAL_AVAILABILITY"
    DEPRECATION_ANNOUNCED = "DEPRECATION_ANNOUNCED"
    SUNSET = "SUNSET"


# ---------------------------------------------------------------- application enums
class AccessTier(str, Enum):
    SANDBOX = "SANDBOX"
    STANDARD = "STANDARD"
    PARTNER = "PARTNER"
    PRIVILEGED = "PRIVILEGED"


class ApplicationState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ----------------------------------------------------------------- entitlement enums
class EntitlementState(str, Enum):
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ThrottleState(str, Enum):
    NORMAL = "NORMAL"
    SOFT_THROTTLED = "SOFT_THROTTLED"
    HARD_THROTTLED = "HARD_THROTTLED"


class AttributionVariant(str, Enum):
    BURST_ISOLATED = "BURST_ISOLATED"
    BURST_INCLUSIVE = "BURST_INCLUSIVE"


class UpgradeRequestState(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
    DEFERRED = "DEFERRED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class DenialReason(str, Enum):
    POOL_EXHAUSTED = "POOL_EXHAUSTED"
    STANDING_BLOCKED = "STANDING_BLOCKED"


# --------------------------------------------------------------------- lease enums
class LeaseState(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LeaseClosedReason(str, Enum):
    DEVELOPER_RELEASE = "DEVELOPER_RELEASE"
    CHECKPOINT_EXPIRY = "CHECKPOINT_EXPIRY"
    STANDING_CASCADE = "STANDING_CASCADE"


# ---------------------------------------------------------------- enforcement enums
class ViolationCategory(str, Enum):
    RATE_ABUSE = "RATE_ABUSE"
    SCOPE_OVERREACH = "SCOPE_OVERREACH"
    DATA_RETENTION = "DATA_RETENTION"
    RESALE = "RESALE"


class ViolationSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CaseState(str, Enum):
    OPENED = "OPENED"
    INVESTIGATING = "INVESTIGATING"
    UPHELD = "UPHELD"
    APPEALED = "APPEALED"
    UPHELD_FINAL = "UPHELD_FINAL"
    DISMISSED = "DISMISSED"


class CaseOutcome(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


# ------------------------------------------------------------------- support enums
class SupportCaseKind(str, Enum):
    PARTNER_TICKET = "PARTNER_TICKET"
    PLATFORM_INCIDENT = "PLATFORM_INCIDENT"


class SupportSeverity(str, Enum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"


class SupportCaseState(str, Enum):
    OPEN = "OPEN"
    RESPONDING = "RESPONDING"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


# ------------------------------------------------------------------ feedback enums
class FeedbackCategory(str, Enum):
    DEFECT = "DEFECT"
    MISSING_FEATURE = "MISSING_FEATURE"
    DX_FRICTION = "DX_FRICTION"
    DOC_GAP = "DOC_GAP"


class FeedbackState(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    ROADMAP_ACCEPTED = "ROADMAP_ACCEPTED"
    DECLINED = "DECLINED"


class AuthorTopTier(str, Enum):
    NONE = "NONE"
    SANDBOX = "SANDBOX"
    STANDARD = "STANDARD"
    PARTNER = "PARTNER"
    PRIVILEGED = "PRIVILEGED"


# --------------------------------------------------------------- decision literals
DECISION_REASON_TARGET_VERSION_SUNSET = "TARGET_VERSION_SUNSET"
DECISION_REASON_REVISION_LIMIT_EXHAUSTED = "REVISION_LIMIT_EXHAUSTED"
DECISION_REASON_ACCESS_REVOKED = "ACCESS_REVOKED"
SUSPENSION_REASON_STANDING_RESTRICTION = "STANDING_RESTRICTION"


# ------------------------------------------------------------------ entity payloads
class Developer(TypedDict):
    id: str
    org_name: str
    contact_email: str
    region_code: str
    onboarding_state: str
    standing: str
    directory_state: str
    directory_summary: Optional[str]
    docs_version_acknowledged: Optional[int]
    tos_version_accepted: Optional[int]
    certification_level: str
    certification_expires_at: Optional[str]
    hackathon_award_count: int
    clean_window_count: int
    throttled_window_count: int
    violation_points: int
    trust_score: int
    audited_trust_score: int
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApiProduct(TypedDict):
    id: str
    name: str
    data_sensitivity: str
    scope_catalog: List[dict]
    sample_app_slugs: List[str]
    sustained_rpm_pool: int
    monthly_call_pool: int
    allocated_sustained_rpm: int
    allocated_monthly_calls: int
    available_sustained_rpm: int
    available_monthly_calls: int
    required_tos_version: int
    demand_index: float
    created_at: str
    updated_at: str
    version: int


class ApiVersion(TypedDict):
    id: str
    api_product_id: str
    semver: str
    lifecycle_state: str
    breaking_change: bool
    migration_guide_url: Optional[str]
    migration_guide_published_at: Optional[str]
    deprecation_announced_at: Optional[str]
    sunset_at: Optional[str]
    required_notice_days: Optional[int]
    notice_days_at_announcement: Optional[int]
    sunset_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessApplication(TypedDict):
    id: str
    developer_id: str
    target_api_version_id: str
    requested_tier: str
    requested_scopes: List[str]
    requested_monthly_calls: int
    justification_text: Optional[str]
    state: str
    revision_round: int
    reviewer_user_id: Optional[str]
    approver_user_id: Optional[str]
    approved_tier: Optional[str]
    granted_scopes: Optional[List[str]]
    data_access_limit: Optional[str]
    changes_requested_note: Optional[str]
    decision_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuotaAssignment(TypedDict):
    id: str
    developer_id: str
    access_application_id: str
    pinned_api_version_id: str
    tier: str
    granted_scopes: List[str]
    sustained_rpm: int
    burst_rpm: int
    burst_credit_balance: int
    monthly_call_allowance: int
    bonus_call_credit: int
    monthly_calls_consumed: int
    entitlement_state: str
    throttle_state: str
    trust_multiplier_applied: float
    activated_at: Optional[str]
    suspended_at: Optional[str]
    suspension_reason: Optional[str]
    retired_at: Optional[str]
    last_reset_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UpgradeRequest(TypedDict):
    id: str
    quota_assignment_id: str
    requested_sustained_rpm: int
    justification_text: str
    requested_delta_rpm: int
    granted_delta_rpm: int
    state: str
    denial_reason: Optional[str]
    run_sequence: Optional[int]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UsageWindow(TypedDict):
    """A usage window is an immutable measurement record: only id and created_at."""
    id: str
    quota_assignment_id: str
    window_start: str
    window_end: str
    total_calls: int
    burst_calls: int
    attribution_variant: str
    calls_charged_to_allowance: int
    burst_credit_consumed: int
    monthly_calls_consumed_after: int
    overage_calls: int
    rate_limit_breach: bool
    resulting_throttle_state: str
    created_at: str


class SandboxLease(TypedDict):
    id: str
    developer_id: str
    api_product_id: str
    starts_at: str
    lease_days: int
    expires_at: str
    sample_app_slug: str
    state: str
    released_at: Optional[str]
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ViolationCase(TypedDict):
    id: str
    developer_id: str
    quota_assignment_id: Optional[str]
    category: str
    severity: str
    summary: str
    evidence_window_ids: Optional[List[str]]
    state: str
    penalty_points: int
    points_applied: int
    opened_by_user_id: str
    investigator_user_id: Optional[str]
    adjudicator_user_id: Optional[str]
    remediation_deadline: Optional[str]
    appeal_deadline: Optional[str]
    outcome: Optional[str]
    appeal_reason: Optional[str]
    appeal_count: int
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupportCase(TypedDict):
    id: str
    kind: str
    developer_id: Optional[str]
    api_product_id: str
    severity: str
    title: str
    started_at: str
    state: str
    escalation_tier: int
    first_response_due_minutes: int
    first_response_at: Optional[str]
    first_response_breached: bool
    communication_count: int
    last_communication_at: Optional[str]
    max_communication_gap_minutes: int
    comms_gap_breached: bool
    resolved_at: Optional[str]
    downtime_minutes: Optional[int]
    credit_uplift_applied: Optional[float]
    affected_assignment_count: int
    total_credit_calls: int
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeedbackItem(TypedDict):
    id: str
    developer_id: str
    api_product_id: str
    category: str
    body: str
    state: str
    author_top_tier: Optional[str]
    raw_impact: Optional[float]
    priority_score: Optional[float]
    triaged_by_user_id: Optional[str]
    decision_note: Optional[str]
    triaged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
