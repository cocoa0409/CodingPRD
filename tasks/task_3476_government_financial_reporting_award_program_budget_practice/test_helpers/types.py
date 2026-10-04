"""Domain types: entity shapes, status enums, and the role enum (PRD §2.1, §2.5, §3).

Entity shapes mirror the PRD resource model exactly.  Every primary resource
carries ``id`` / ``created_at`` / ``updated_at`` / ``version`` (PRD §2.5); the
review finding is the sole exception — it is immutable and carries only ``id``
and ``created_at``, so its shape deliberately omits ``updated_at`` and
``version``.
"""

from enum import Enum
from typing import Dict, List, Optional, TypedDict

__all__ = [
    "UserRole",
    "ProgramType",
    "GovType",
    "PopulationBand",
    "BudgetDocType",
    "ReviewerStatus",
    "ChecklistStatus",
    "StandardStatus",
    "CyclePosture",
    "SubmissionStatus",
    "AssignmentStatus",
    "CommentSeverity",
    "PublicationStatus",
    "CommentResolution",
    "ProgramLabel",
    "AllocationPolicy",
    "ApplicationPurpose",
    "FundStatus",
    "ApplicationStatus",
    "Government",
    "Member",
    "ReviewerProfile",
    "ChecklistVersion",
    "StandardsReference",
    "AwardCycle",
    "ReportSubmission",
    "ReviewAssignment",
    "ReviewFinding",
    "BestPracticePublication",
    "MemberComment",
    "ScholarshipFund",
    "ScholarshipApplication",
]


# ─── Roles (PRD §2.1) ───────────────────────────────────────────────────────


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    GOVERNMENT_CONTACT = "GovernmentContact"
    REVIEWER = "Reviewer"
    COMMITTEE_MEMBER = "CommitteeMember"
    MEMBER = "Member"
    AWARDS_DIRECTOR = "AwardsDirector"


# ─── Field enums (PRD §3) ───────────────────────────────────────────────────


class ProgramType(str, Enum):
    FINANCIAL_REPORTING = "FINANCIAL_REPORTING"
    BUDGET_PRESENTATION = "BUDGET_PRESENTATION"


class GovType(str, Enum):
    CITY = "CITY"
    COUNTY = "COUNTY"
    STATE_GOV = "STATE_GOV"
    SPECIAL_DISTRICT = "SPECIAL_DISTRICT"


class PopulationBand(str, Enum):
    """Used for both Government.population_band and Member.government_size_band."""

    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class BudgetDocType(str, Enum):
    POLICY = "POLICY"
    FINANCIAL_PLAN = "FINANCIAL_PLAN"
    COMMUNICATION = "COMMUNICATION"


class ReviewerStatus(str, Enum):
    APPLICANT = "APPLICANT"
    TRAINED = "TRAINED"
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ChecklistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class StandardStatus(str, Enum):
    ISSUED = "ISSUED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class CyclePosture(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    PAST_REVIEW = "PAST_REVIEW"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DECISION_READY = "DECISION_READY"
    DECIDED_AWARDED = "DECIDED_AWARDED"
    DECIDED_DENIED = "DECIDED_DENIED"
    APPEALED = "APPEALED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"


class CommentSeverity(str, Enum):
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class PublicationStatus(str, Enum):
    DRAFTING = "DRAFTING"
    MEMBER_COMMENT = "MEMBER_COMMENT"
    RESOLUTION = "RESOLUTION"
    PUBLISHED = "PUBLISHED"


class CommentResolution(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVISED = "REVISED"
    REJECTED = "REJECTED"


class ProgramLabel(str, Enum):
    SCHOLARSHIP = "SCHOLARSHIP"
    TECHNICAL_ASSISTANCE = "TECHNICAL_ASSISTANCE"


class AllocationPolicy(str, Enum):
    FLAT_CAP = "FLAT_CAP"
    PRO_RATA = "PRO_RATA"


class ApplicationPurpose(str, Enum):
    CONFERENCE_SCHOLARSHIP = "CONFERENCE_SCHOLARSHIP"
    TECHNICAL_ASSISTANCE = "TECHNICAL_ASSISTANCE"


class FundStatus(str, Enum):
    ALLOCATING = "ALLOCATING"
    EXHAUSTED = "EXHAUSTED"


class ApplicationStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    RESCINDED = "RESCINDED"


# ─── Entity shapes (PRD §2.5 common fields + §3 resource fields) ────────────


class Government(TypedDict):
    id: str
    legal_name: str
    gov_type: str
    population_band: str
    state_code: str
    lifetime_award_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    government_size_band: str
    independent_finance_officer: bool
    annual_dues_cents: int
    created_at: str
    updated_at: str
    version: int


class ReviewerProfile(TypedDict):
    id: str
    member_id: str
    employer_government_id: str
    conflicted_government_ids: List[str]
    unavailability_windows: List[Dict[str, str]]
    independence_attested: bool
    status: str
    trained_at: Optional[str]
    open_assignment_count: int
    completed_review_count: int
    declined_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class ChecklistVersion(TypedDict):
    id: str
    program_type: str
    version_label: str
    pass_score: float
    criteria: List[Dict[str, object]]
    status: str
    created_at: str
    updated_at: str
    version: int


class StandardsReference(TypedDict):
    id: str
    topic_code: str
    title: str
    program_type: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AwardCycle(TypedDict):
    id: str
    program_type: str
    fiscal_year: int
    submission_opens_at: str
    submission_deadline_at: str
    review_close_at: str
    checklist_version_id: str
    posture: str
    submitted_count: int
    decision_ready_count: int
    conferred_count: int
    created_at: str
    updated_at: str
    version: int


class ReportSubmission(TypedDict):
    id: str
    government_id: str
    cycle_id: str
    budget_documents: List[Dict[str, object]]
    program_type: str
    pinned_checklist_version_id: str
    pinned_checklist_stale: bool
    appeal_round: int
    status: str
    provisional_score: Optional[float]
    final_score: Optional[float]
    major_deficiency_total: int
    required_improvements: List[str]
    award_conferred: bool
    submitted_at: Optional[str]
    decided_at: Optional[str]
    conferred_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewAssignment(TypedDict):
    id: str
    submission_id: str
    # Masked to null for GovernmentContact readers (PRD §2.11).
    reviewer_id: Optional[str]
    reviewer_alias: str
    appeal_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewFinding(TypedDict):
    """Immutable record (PRD §2.5): carries only id + created_at from the
    common set — no updated_at, no version."""

    id: str
    created_at: str
    assignment_id: str
    appeal_round: int
    criterion_scores: List[Dict[str, object]]
    comments: List[Dict[str, object]]
    weighted_score: float
    major_deficiency_count: int


class BestPracticePublication(TypedDict):
    id: str
    committee_name: str
    chair_member_id: str
    member_ids: List[str]
    created_by_member_id: str
    title: str
    topic_code: str
    pinned_standards_reference_id: Optional[str]
    comment_window_opens_at: Optional[str]
    comment_window_closes_at: Optional[str]
    draft_number: int
    pending_comment_count: int
    resolved_comment_count: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MemberComment(TypedDict):
    id: str
    publication_id: str
    member_id: str
    body: str
    resolution: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScholarshipFund(TypedDict):
    id: str
    fiscal_year: int
    program_label: str
    pool_total_cents: int
    per_applicant_cap_cents: int
    allocation_policy: str
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScholarshipApplication(TypedDict):
    id: str
    fund_id: str
    government_id: str
    purpose: str
    requested_cents: int
    granted_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
