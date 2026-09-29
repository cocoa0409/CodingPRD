"""Domain types for the LMS Shell & Term Rollover API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    LMS_ADMIN = "LmsAdmin"
    INSTRUCTOR = "Instructor"
    PRIVACY_REVIEWER = "PrivacyReviewer"
    ACCESSIBILITY_REVIEWER = "AccessibilityReviewer"
    STUDENT = "Student"


# ─── State enums ──────────────────────────────────────────────────────────

class TermLifecycleState(str, Enum):
    PLANNING = "PLANNING"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    IN_SESSION = "IN_SESSION"
    FINALS = "FINALS"
    GRADING = "GRADING"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class ContinuityPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    CONTINUITY_MODE = "CONTINUITY_MODE"


class RetentionClass(str, Enum):
    STANDARD = "STANDARD"
    EXTENDED = "EXTENDED"
    LEGAL_HOLD = "LEGAL_HOLD"


class PrimaryAffiliation(str, Enum):
    STUDENT = "STUDENT"
    FACULTY = "FACULTY"
    STAFF = "STAFF"


class ShellType(str, Enum):
    OFFICIAL = "OFFICIAL"
    SANDBOX = "SANDBOX"
    DEV = "DEV"


class ProvisioningState(str, Enum):
    REQUESTED = "REQUESTED"
    PROVISIONED = "PROVISIONED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    MERGED = "MERGED"
    CONCLUDED = "CONCLUDED"
    ARCHIVED = "ARCHIVED"
    PURGED = "PURGED"


class EnrollmentRole(str, Enum):
    STUDENT = "STUDENT"
    TEACHER = "TEACHER"
    TA = "TA"
    DESIGNER = "DESIGNER"
    OBSERVER = "OBSERVER"


class EnrollmentState(str, Enum):
    ACTIVE = "ACTIVE"
    WAITLISTED = "WAITLISTED"
    DROPPED = "DROPPED"
    COMPLETED = "COMPLETED"


class BatchState(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    APPLIED = "APPLIED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MergeState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class ItemType(str, Enum):
    ASSIGNMENT = "ASSIGNMENT"
    QUIZ = "QUIZ"
    PAGE = "PAGE"
    FILE = "FILE"


class CopyState(str, Enum):
    SOURCE = "SOURCE"
    COPIED = "COPIED"
    SKIPPED = "SKIPPED"


class JobState(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    COPYING = "COPYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    COMPENSATED = "COMPENSATED"


class DateShiftMode(str, Enum):
    ANCHOR_PROPORTIONAL = "ANCHOR_PROPORTIONAL"
    FIXED_OFFSET = "FIXED_OFFSET"


class DataSharingScope(str, Enum):
    NONE = "NONE"
    ROSTER_ONLY = "ROSTER_ONLY"
    ROSTER_AND_GRADES = "ROSTER_AND_GRADES"
    FULL_PROFILE = "FULL_PROFILE"


class WcagLevel(str, Enum):
    NONE = "NONE"
    A = "A"
    AA = "AA"
    AAA = "AAA"


class ReviewDimensionState(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    CONDITIONAL = "CONDITIONAL"
    BLOCKED = "BLOCKED"


class ApprovalState(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class ReviewDimension(str, Enum):
    PRIVACY = "PRIVACY"
    ACCESSIBILITY = "ACCESSIBILITY"


class ReviewDecision(str, Enum):
    CLEAR = "CLEAR"
    CONDITIONS = "CONDITIONS"
    BLOCK = "BLOCK"


class PlacementState(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    REMOVED = "REMOVED"


class PassbackState(str, Enum):
    STAGED = "STAGED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
    DISPUTED = "DISPUTED"
    AMENDED = "AMENDED"


class GradeVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class DisputeState(str, Enum):
    OPEN = "OPEN"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_CHANGED = "RESOLVED_CHANGED"


class WindowKind(str, Enum):
    OUTAGE = "OUTAGE"
    EXTENSION = "EXTENSION"
    MAINTENANCE = "MAINTENANCE"


class WindowState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


# ─── Entity shapes ─────────────────────────────────────────────────────────
# Every record carries id + created_at (PRD §2.4). Almost every record also
# carries updated_at + version; ToolReview is the single exception and carries
# id and created_at only.

class AcademicTerm(TypedDict):
    id: str
    term_code: str
    lifecycle_state: str
    continuity_posture: str
    term_start_at: str
    term_end_at: str
    add_drop_deadline_at: str
    finals_window_start_at: str
    finals_window_end_at: str
    access_grace_days: int
    retention_class: str
    student_access_end_at: str
    retention_purge_at: Optional[str]
    rollover_completion_pct: float
    published_shell_count: int
    overflow_shell_count: int
    total_active_enrollments: int
    open_amendment_count: int
    sis_sync_epoch: int
    created_at: str
    updated_at: str
    version: int


class Person(TypedDict):
    id: str
    sis_person_id: str
    full_name: str
    primary_affiliation: str
    ferpa_block: bool
    access_revoked_at: Optional[str]
    sandbox_storage_charge_usd: float
    created_at: str
    updated_at: str
    version: int


class CourseShell(TypedDict):
    id: str
    term_id: str
    owner_person_id: str
    sis_section_code: str
    shell_type: str
    provisioning_state: str
    base_seat_cap: int
    effective_seat_cap: int
    active_enrollment_count: int
    waitlisted_enrollment_count: int
    seat_utilization_pct: float
    overflow_flag: bool
    storage_mb: float
    merged_into_shell_id: Optional[str]
    absorbed_child_count: int
    content_item_count: int
    total_points_possible: float
    blocked_placement_count: int
    publish_readiness: bool
    sandbox_expires_at: Optional[str]
    reject_reason: Optional[str]
    unpublish_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    shell_id: str
    person_id: str
    batch_id: Optional[str]
    merged_from_shell_id: Optional[str]
    role: str
    enrollment_state: str
    waitlist_position: Optional[int]
    earned_points_total: float
    graded_points_possible: float
    provisional_grade_pct: float
    final_grade_pct: Optional[float]
    dropped_at: Optional[str]
    reinstatement_count: int
    disputed_points_held: float
    created_at: str
    updated_at: str
    version: int


class EnrollmentSyncBatch(TypedDict):
    id: str
    term_id: str
    batch_seq: int
    operations: List[dict]
    batch_state: str
    validated_operation_count: int
    rejected_operation_count: int
    applied_add_count: int
    applied_drop_count: int
    promoted_from_waitlist_count: int
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MergeRequest(TypedDict):
    id: str
    parent_shell_id: str
    child_shell_id: str
    justification: str
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    merge_state: str
    moved_enrollment_count: int
    reversed_enrollment_count: int
    seat_ledger_before: Optional[int]
    seat_ledger_after: int
    created_at: str
    updated_at: str
    version: int


class ContentItem(TypedDict):
    id: str
    shell_id: str
    source_item_id: Optional[str]
    item_type: str
    title: str
    due_at: Optional[str]
    points_possible: float
    storage_mb: float
    has_submissions: bool
    submission_count: int
    date_stripped: bool
    copy_state: str
    created_at: str
    updated_at: str
    version: int


class RolloverJob(TypedDict):
    id: str
    source_shell_id: str
    target_shell_id: str
    target_term_id: str
    strip_dates: bool
    strip_submissions: bool
    strip_grades: bool
    date_shift_mode: str
    job_state: str
    eligible_item_count: int
    copied_item_count: int
    skipped_item_count: int
    date_stripped_count: int
    date_shifted_count: int
    copied_storage_mb: float
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ToolIntegration(TypedDict):
    id: str
    vendor_name: str
    tool_name: str
    tool_version: str
    data_sharing_scope: str
    pii_tier: int
    vpat_score: float
    wcag_level: str
    privacy_review_state: str
    accessibility_review_state: str
    approval_state: str
    risk_score: Optional[float]
    approved_version: Optional[str]
    active_placement_count: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ToolReview(TypedDict):
    """Immutable review verdict: carries id and created_at only (PRD §2.4)."""
    id: str
    tool_id: str
    dimension: str
    decision: str
    reviewer_user_id: str
    conditions_note: Optional[str]
    created_at: str


class ToolPlacement(TypedDict):
    id: str
    tool_id: str
    shell_id: str
    placement_state: str
    pinned_tool_version: Optional[str]
    blocked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GradePassback(TypedDict):
    id: str
    shell_id: str
    term_id: str
    passback_state: str
    variant_applied: str
    staged_enrollment_count: int
    submitted_points_total: float
    accepted_points_total: float
    disputed_points_held: float
    open_dispute_count: int
    amendment_round: int
    registrar_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GradeDispute(TypedDict):
    id: str
    passback_id: str
    enrollment_id: str
    content_item_id: str
    claimed_earned_points: float
    dispute_state: str
    held_points: float
    adjusted_earned_points: Optional[float]
    filed_by_user_id: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContinuityWindow(TypedDict):
    id: str
    term_id: str
    shell_id: Optional[str]
    kind: str
    window_start: str
    window_end: str
    window_state: str
    affected_enrollment_count: int
    extension_days_granted: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
