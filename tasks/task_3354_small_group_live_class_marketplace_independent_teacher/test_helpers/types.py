"""Domain types: status enums, role enum and entity TypedDicts (PRD §2.5, §3).

Every top-level resource in this API carries `id`, `created_at`, `updated_at` and
`version`; there are no exceptions (PRD §2.5), so all eight TypedDicts below
declare the full common-field set.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    TEACHER_APPLICANT = "TeacherApplicant"
    TEACHER_REVIEWER = "TeacherReviewer"
    TEACHER = "Teacher"
    PARENT = "Parent"
    PLATFORM_ADMIN = "PlatformAdmin"


class TeacherApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENING_PENDING = "SCREENING_PENDING"
    SCREENING_FAILED = "SCREENING_FAILED"
    SCREENING_PASSED = "SCREENING_PASSED"
    SAMPLE_PENDING = "SAMPLE_PENDING"
    SAMPLE_REJECTED = "SAMPLE_REJECTED"
    SAMPLE_APPROVED = "SAMPLE_APPROVED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TeacherStatus(str, Enum):
    PENDING_SETUP = "PENDING_SETUP"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ClassFormat(str, Enum):
    ONE_TIME = "ONE_TIME"
    MULTI_DAY = "MULTI_DAY"
    ONGOING = "ONGOING"


class ContentReviewState(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    POLICY_APPROVED = "POLICY_APPROVED"
    POLICY_REJECTED = "POLICY_REJECTED"


class ListingLifecycleState(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class SectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN_FOR_ENROLLMENT = "OPEN_FOR_ENROLLMENT"
    MIN_ENROLLMENT_MET = "MIN_ENROLLMENT_MET"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class SectionOutcome(str, Enum):
    HELD = "HELD"
    AUTO_CANCELLED_MIN_ENROLLMENT = "AUTO_CANCELLED_MIN_ENROLLMENT"
    AUTO_CANCELLED_SEAT_LOSS = "AUTO_CANCELLED_SEAT_LOSS"
    CANCELLED_BY_TEACHER = "CANCELLED_BY_TEACHER"


class EnrollmentStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    CANCELLED_BY_TEACHER = "CANCELLED_BY_TEACHER"


class RefundCategory(str, Enum):
    NONE = "NONE"
    PARTIAL_HALF = "PARTIAL_HALF"
    FULL = "FULL"


class SubscriptionTier(str, Enum):
    NONE = "NONE"
    PLUS = "PLUS"
    FAMILY = "FAMILY"


class PayoutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SENT = "SENT"
    FAILED = "FAILED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"


class TaxDocumentStatus(str, Enum):
    ON_FILE = "ON_FILE"
    REQUIRED_UPDATE = "REQUIRED_UPDATE"
    EXPIRED = "EXPIRED"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ReportDisposition(str, Enum):
    DISMISSED = "DISMISSED"
    WARNING = "WARNING"
    MORE_SEVERE = "MORE_SEVERE"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReportCategory(str, Enum):
    CONTENT_POLICY = "CONTENT_POLICY"
    SAFETY = "SAFETY"
    CONDUCT = "CONDUCT"
    TECHNICAL = "TECHNICAL"
    OTHER = "OTHER"


class TeacherApplication(TypedDict, total=False):
    id: str
    applicant_user_id: str
    applicant_email: str
    display_name: str
    status: str
    screening_outcome: Optional[str]
    screening_is_stale: bool
    screening_completed_period_index: Optional[int]
    teaching_sample_url: Optional[str]
    teaching_sample_minutes: int
    reviewed_by_user_id: Optional[str]
    reviewer_bound_period_index: Optional[int]
    decision: Optional[str]
    decision_reason_code: Optional[str]
    revision_count: int
    eligible_for_appeal: bool
    created_at: str
    updated_at: str
    version: int


class Teacher(TypedDict, total=False):
    id: str
    application_id: str
    display_name: str
    status: str
    screening_validity_period_index: int
    payout_tax_document_status: str
    suspension_reason: Optional[str]
    suspension_trigger: Optional[str]
    open_report_count: int
    open_report_risk_score: int
    upheld_report_risk_score: int
    actionable_risk_score: int
    peak_actionable_risk_score: int
    lifetime_net_earnings_cents: int
    lifetime_fee_reversed_cents: int
    lifetime_teacher_liability_cents: int
    unpaid_earnings_cents: int
    re_screen_required: bool
    created_at: str
    updated_at: str
    version: int


class ClassListing(TypedDict, total=False):
    id: str
    teacher_id: str
    title: str
    format: str
    min_age: int
    max_age: int
    max_learners: int
    list_price_cents: int
    content_review_state: str
    policy_rejection_reason_code: Optional[str]
    lifecycle_state: str
    listing_sequence: int
    section_count: int
    created_at: str
    updated_at: str
    version: int


class Section(TypedDict, total=False):
    id: str
    class_listing_id: str
    timezone: str
    start_utc: str
    end_utc: str
    min_learners: int
    capacity: int
    expected_learners: Optional[int]
    status: str
    scheduled_start_confirmed: bool
    settled: bool
    enrolled_count: int
    reserved_count: int
    seats_remaining: int
    enrollment_min_met: bool
    outcome: Optional[str]
    cancellation_cutoff_utc: str
    created_at: str
    updated_at: str
    version: int


class Learner(TypedDict, total=False):
    id: str
    display_name: str
    birth_date: str
    parent_user_id: str
    subscription_tier: str
    subscription_discount_pct: float
    confirmation_credit_cents: int
    enrollment_sequence: int
    abuse_strike_count: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    section_id: str
    learner_id: str
    status: str
    coupon_code: Optional[str]
    coupon_discount_cents: int
    subscription_discount_cents: int
    discounted_price_cents: int
    refund_category: Optional[str]
    refund_cents: int
    cancelled_by: Optional[str]
    credit_applied_cents: int
    cash_refund_cents: int
    created_at: str
    updated_at: str
    version: int


class TeacherPayout(TypedDict, total=False):
    id: str
    teacher_id: str
    period_start: str
    period_end: str
    status: str
    gross_earnings_cents: int
    fee_rate_applied: float
    platform_fee_cents: int
    net_payout_cents: int
    net_after_refunds_cents: int
    payout_proration_factor: float
    approval_status: str
    tax_document_status: str
    refund_period_index: Optional[int]
    teacher_liability_cents: int
    platform_fee_reversed_cents: int
    created_at: str
    updated_at: str
    version: int


class ParentReport(TypedDict, total=False):
    id: str
    teacher_id: str
    class_listing_id: str
    reported_by_user_id: str
    severity: str
    category: str
    severity_weight: int
    status: str
    disposition: Optional[str]
    high_severity: bool
    is_terminal: bool
    created_at: str
    updated_at: str
    version: int


ALL_STATUS_ENUMS: List[str] = [
    "TeacherApplicationStatus",
    "TeacherStatus",
    "ClassFormat",
    "ContentReviewState",
    "ListingLifecycleState",
    "SectionStatus",
    "EnrollmentStatus",
    "PayoutStatus",
    "ReportStatus",
]
