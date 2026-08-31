"""Domain types for the Screenplay Coverage & Development Slate API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    SLATE_ADMIN = "SlateAdmin"
    STORY_EDITOR = "StoryEditor"
    SUBMITTER = "Submitter"
    READER = "Reader"
    BUSINESS_AFFAIRS = "BusinessAffairs"
    DEVELOPMENT_EXEC = "DevelopmentExec"
    WRITER = "Writer"
    COMMITTEE_MEMBER = "CommitteeMember"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class MaterialType(str, Enum):
    SPEC_SCRIPT = "SPEC_SCRIPT"
    BOOK = "BOOK"
    ARTICLE = "ARTICLE"
    PLAY = "PLAY"
    LIFE_RIGHTS_STORY = "LIFE_RIGHTS_STORY"
    ORIGINAL_PITCH = "ORIGINAL_PITCH"


class Genre(str, Enum):
    DRAMA = "DRAMA"
    COMEDY = "COMEDY"
    THRILLER = "THRILLER"
    HORROR = "HORROR"
    SCIFI = "SCIFI"
    FAMILY = "FAMILY"
    DOCUMENTARY = "DOCUMENTARY"


class RightsChainStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PARTIAL = "PARTIAL"
    CLEAR = "CLEAR"
    DISPUTED = "DISPUTED"


class TrackingTier(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    HOT = "HOT"
    PRIORITY = "PRIORITY"


class DocType(str, Enum):
    CHAIN_OF_TITLE = "CHAIN_OF_TITLE"
    COPYRIGHT_CERT = "COPYRIGHT_CERT"
    WGA_REGISTRATION = "WGA_REGISTRATION"
    PRIOR_ASSIGNMENT = "PRIOR_ASSIGNMENT"
    LIFE_RIGHTS_RELEASE = "LIFE_RIGHTS_RELEASE"
    CLEARANCE_OPINION = "CLEARANCE_OPINION"


class SubmittedVia(str, Enum):
    AGENCY = "AGENCY"
    MANAGER = "MANAGER"
    ATTORNEY = "ATTORNEY"
    UNSOLICITED = "UNSOLICITED"
    INTERNAL = "INTERNAL"


class PriorityFlag(str, Enum):
    RUSH = "RUSH"
    STANDARD = "STANDARD"
    BACKLOG = "BACKLOG"


class SubmissionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RELEASE_PENDING = "RELEASE_PENDING"
    INTAKE_CLEARED = "INTAKE_CLEARED"
    READER_ASSIGNED = "READER_ASSIGNED"
    COVERAGE_IN_REVIEW = "COVERAGE_IN_REVIEW"
    TRACKED = "TRACKED"
    PASSED = "PASSED"
    IN_DEVELOPMENT = "IN_DEVELOPMENT"
    WITHDRAWN = "WITHDRAWN"


class SubmissionDecision(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    CONSIDER = "CONSIDER"
    RECOMMEND = "RECOMMEND"
    STRONG_RECOMMEND = "STRONG_RECOMMEND"


class ReleaseFormStatus(str, Enum):
    REQUIRED = "REQUIRED"
    SENT = "SENT"
    EXECUTED = "EXECUTED"
    WAIVED = "WAIVED"
    EXPIRED = "EXPIRED"


class EmploymentType(str, Enum):
    STAFF = "STAFF"
    FREELANCE = "FREELANCE"


class ReaderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    RECALLED = "RECALLED"


class Recommendation(str, Enum):
    PASS = "PASS"
    CONSIDER = "CONSIDER"
    RECOMMEND = "RECOMMEND"
    STRONG_RECOMMEND = "STRONG_RECOMMEND"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BoardEntryStatus(str, Enum):
    LIVE = "LIVE"
    ARCHIVED = "ARCHIVED"


class OptionStatus(str, Enum):
    DRAFTED = "DRAFTED"
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    EXERCISED = "EXERCISED"
    LAPSED = "LAPSED"
    REVERTED = "REVERTED"
    TERMINATED = "TERMINATED"


class RightsStatus(str, Enum):
    OPTIONED = "OPTIONED"
    OWNED = "OWNED"
    LAPSED_RIGHTS = "LAPSED_RIGHTS"
    REVERTED = "REVERTED"


class DevelopmentStatus(str, Enum):
    SETUP = "SETUP"
    WRITING = "WRITING"
    DRAFT_DELIVERED = "DRAFT_DELIVERED"
    POLISH = "POLISH"
    POLISH_DELIVERED = "POLISH_DELIVERED"
    GREENLIT = "GREENLIT"
    TURNAROUND = "TURNAROUND"
    DEAD = "DEAD"


class WriterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNAVAILABLE = "UNAVAILABLE"


class EngagementType(str, Enum):
    ORIGINAL_DRAFT = "ORIGINAL_DRAFT"
    REWRITE = "REWRITE"
    POLISH = "POLISH"
    PRODUCTION_REWRITE = "PRODUCTION_REWRITE"


class EngagementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ATTACHED = "ATTACHED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class MilestoneType(str, Enum):
    COMMENCEMENT = "COMMENCEMENT"
    FIRST_DRAFT_DELIVERY = "FIRST_DRAFT_DELIVERY"
    FIRST_DRAFT_ACCEPTANCE = "FIRST_DRAFT_ACCEPTANCE"
    REWRITE_DELIVERY = "REWRITE_DELIVERY"
    POLISH_DELIVERY = "POLISH_DELIVERY"
    PRODUCTION_BONUS = "PRODUCTION_BONUS"


class MilestoneStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    VOTING = "VOTING"
    PASSED = "PASSED"
    DECLINED = "DECLINED"
    DEFERRED = "DEFERRED"
    WITHDRAWN = "WITHDRAWN"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class VoteValue(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    ABSTAIN = "ABSTAIN"
    VETO = "VETO"


# --------------------------------------------------------------------------
# Entities that carry id + created_at + updated_at + version
# --------------------------------------------------------------------------


class LiteraryProperty(TypedDict):
    id: str
    title: str
    material_type: str
    source_author_name: str
    genre: str
    logline: str
    rights_chain_status: str
    verified_document_count: int
    tracking_tier: str
    encumbrance_count: int
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    property_id: str
    submitting_agency: str
    submitter_contact_email: str
    submitted_via: str
    priority_flag: str
    release_form_required: bool
    received_at: str
    coverage_due_at: str
    status: str
    decision: str
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReleaseForm(TypedDict):
    id: str
    submission_id: str
    status: str
    expires_at: str
    signer_name: Optional[str]
    signed_at: Optional[str]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reader(TypedDict):
    id: str
    display_name: str
    specialty_genre: str
    weekly_capacity: int
    employment_type: str
    status: str
    active_assignment_count: int
    completed_report_count: int
    calibration_bias: float
    created_at: str
    updated_at: str
    version: int


class CoverageAssignment(TypedDict):
    id: str
    submission_id: str
    reader_id: str
    assigned_by_user_id: str
    window_start: str
    window_due: str
    status: str
    recall_reason: Optional[str]
    auto_selected: bool
    created_at: str
    updated_at: str
    version: int


class CoverageReport(TypedDict):
    id: str
    assignment_id: str
    logline_score: Optional[int]
    structure_score: Optional[int]
    character_score: Optional[int]
    dialogue_score: Optional[int]
    marketability_score: Optional[int]
    recommendation: Optional[str]
    synopsis_word_count: int
    comparable_titles: List[str]
    composite_score: Optional[float]
    normalized_score: Optional[float]
    revision_round_count: int
    revision_note: Optional[str]
    status: str
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrackingBoardEntry(TypedDict):
    id: str
    property_id: str
    report_id: str
    board_tier: str
    heat_score: float
    competing_submission_count: int
    entered_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OptionAgreement(TypedDict):
    id: str
    property_id: str
    option_fee_cents: int
    purchase_price_cents: int
    initial_period_months: int
    extension_period_months: int
    extension_fee_cents: int
    applicable_to_purchase: bool
    option_start_at: str
    option_end_at: Optional[str]
    extension_exercised: bool
    escalation_bps: int
    adjusted_purchase_price_cents: Optional[int]
    applicable_credit_cents: int
    net_purchase_due_cents: Optional[int]
    status: str
    termination_reason: Optional[str]
    exercise_notice_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DevelopmentProject(TypedDict):
    id: str
    property_id: str
    option_agreement_id: str
    owning_exec_user_id: str
    budget_cents: int
    slate_year: int
    rights_status: str
    development_status: str
    committed_writer_fee_cents: int
    writer_budget_cap_cents: int
    turnaround_start_at: Optional[str]
    turnaround_eligible_at: Optional[str]
    turnaround_reason: Optional[str]
    greenlight_ready: bool
    created_at: str
    updated_at: str
    version: int


class Writer(TypedDict):
    id: str
    name: str
    guild_member: bool
    quote_cents: int
    status: str
    committed_fee_cents: int
    paid_fee_cents: int
    active_engagement_count: int
    created_at: str
    updated_at: str
    version: int


class WriterEngagement(TypedDict):
    id: str
    project_id: str
    writer_id: str
    engagement_type: str
    total_fee_cents: int
    start_date: str
    end_date: str
    status: str
    guild_minimum_cents: int
    milestone_count: int
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MilestonePayment(TypedDict):
    id: str
    engagement_id: str
    milestone_type: str
    sequence_index: int
    percentage_bps: int
    gross_amount_cents: int
    status: str
    due_on: str
    approved_by_user_id: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GreenlightReview(TypedDict):
    id: str
    project_id: str
    session_date: str
    status: str
    eligible_weight_bps: int
    cast_weight_bps: int
    decisive_weight_bps: int
    approve_weight_bps: int
    quorum_pct: float
    approval_pct: float
    veto_cast: bool
    decision_note: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict):
    id: str
    display_name: str
    vote_weight_bps: int
    veto_power: bool
    exec_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only records: id + created_at only, never updated_at, never version
# --------------------------------------------------------------------------


class RightsChainDocument(TypedDict):
    id: str
    property_id: str
    doc_type: str
    executed_on: str
    verified: bool
    supersedes_document_id: Optional[str]
    notes: str
    superseded: bool
    created_at: str


class CommitteeVote(TypedDict):
    id: str
    review_id: str
    member_id: str
    vote_value: str
    weight_bps_snapshot: int
    comment: Optional[str]
    created_at: str
