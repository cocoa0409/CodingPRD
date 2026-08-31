"""Domain types for the Governance Records API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    BOARD_CLERK = "BoardClerk"
    BOARD_PRESIDENT = "BoardPresident"
    BOARD_MEMBER = "BoardMember"
    POLICY_ANALYST = "PolicyAnalyst"
    SUPERINTENDENT = "Superintendent"
    SCHOOL_PRINCIPAL = "SchoolPrincipal"
    LEGAL_UPDATE_SERVICE = "LegalUpdateService"
    PUBLIC = "Public"


class BoardMemberStatus(str, Enum):
    SEATED = "SEATED"
    RESIGNED = "RESIGNED"
    TERM_EXPIRED = "TERM_EXPIRED"


class BoardOffice(str, Enum):
    PRESIDENT = "PRESIDENT"
    VICE_PRESIDENT = "VICE_PRESIDENT"
    MEMBER = "MEMBER"


class CommitteeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INQUORATE = "INQUORATE"


class CharterType(str, Enum):
    POLICY = "POLICY"
    FINANCE = "FINANCE"
    PERSONNEL = "PERSONNEL"
    AUDIT = "AUDIT"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECUSED = "RECUSED"
    REMOVED = "REMOVED"


class CommitteeRole(str, Enum):
    CHAIR = "CHAIR"
    MEMBER = "MEMBER"


class AssignmentAction(str, Enum):
    RECUSE = "RECUSE"
    REINSTATE = "REINSTATE"
    REMOVE = "REMOVE"


class DisclosureNature(str, Enum):
    FINANCIAL = "FINANCIAL"
    VENDOR = "VENDOR"
    EMPLOYMENT = "EMPLOYMENT"
    FAMILIAL = "FAMILIAL"


class DisclosureStatus(str, Enum):
    RECUSAL_REQUIRED = "RECUSAL_REQUIRED"
    ADVISORY_ONLY = "ADVISORY_ONLY"
    CLEARED = "CLEARED"


class PolicyCategory(str, Enum):
    GOVERNANCE = "GOVERNANCE"
    INSTRUCTION = "INSTRUCTION"
    PERSONNEL = "PERSONNEL"
    STUDENTS = "STUDENTS"
    BUSINESS = "BUSINESS"


class LegalRequirementLevel(str, Enum):
    REQUIRED_BY_LAW = "REQUIRED_BY_LAW"
    RECOMMENDED = "RECOMMENDED"
    LOCAL_DISCRETION = "LOCAL_DISCRETION"


class PolicyStatus(str, Enum):
    UNADOPTED = "UNADOPTED"
    ADOPTED = "ADOPTED"


class ComplianceState(str, Enum):
    COMPLIANT = "COMPLIANT"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    NON_COMPLIANT = "NON_COMPLIANT"


class PolicyVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    FIRST_READING_PASSED = "FIRST_READING_PASSED"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class MandateStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    OVERDUE = "OVERDUE"
    SATISFIED = "SATISFIED"


class RequiredAction(str, Enum):
    ADOPT_NEW = "ADOPT_NEW"
    REVISE_EXISTING = "REVISE_EXISTING"
    RESCIND = "RESCIND"


class MeetingScope(str, Enum):
    FULL_BOARD = "FULL_BOARD"
    COMMITTEE = "COMMITTEE"


class MeetingType(str, Enum):
    REGULAR = "REGULAR"
    SPECIAL = "SPECIAL"
    EMERGENCY = "EMERGENCY"


class MeetingStatus(str, Enum):
    DRAFT = "DRAFT"
    NOTICED = "NOTICED"
    OPEN = "OPEN"
    ADJOURNED = "ADJOURNED"


class MinutesStatus(str, Enum):
    NOT_DRAFTED = "NOT_DRAFTED"
    DRAFTED = "DRAFTED"
    APPROVED = "APPROVED"


class MinutesAction(str, Enum):
    DRAFT = "DRAFT"
    APPROVE = "APPROVE"


class PublicCommentRule(str, Enum):
    FIRST_COME_CAPPED = "FIRST_COME_CAPPED"
    EQUAL_SPLIT = "EQUAL_SPLIT"


class AgendaItemType(str, Enum):
    POLICY_FIRST_READING = "POLICY_FIRST_READING"
    POLICY_SECOND_READING = "POLICY_SECOND_READING"
    WAIVER_DECISION = "WAIVER_DECISION"
    SUPERINTENDENT_EVALUATION = "SUPERINTENDENT_EVALUATION"
    CONSENT = "CONSENT"


class AgendaItemStatus(str, Enum):
    PROPOSED = "PROPOSED"
    POSTED = "POSTED"
    ACTED = "ACTED"
    TABLED = "TABLED"
    WITHDRAWN = "WITHDRAWN"


class VoteOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class SpeakerAffiliation(str, Enum):
    PARENT = "PARENT"
    STAFF = "STAFF"
    STUDENT = "STUDENT"
    COMMUNITY = "COMMUNITY"
    VENDOR = "VENDOR"


class PublicCommentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    RELEASED = "RELEASED"


class DenialReason(str, Enum):
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    DUPLICATE_SPEAKER = "DUPLICATE_SPEAKER"
    ITEM_WITHDRAWN = "ITEM_WITHDRAWN"


class WaiverStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    BOARD_PENDING = "BOARD_PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class CommitteeRecommendation(str, Enum):
    RECOMMEND_GRANT = "RECOMMEND_GRANT"
    RECOMMEND_DENY = "RECOMMEND_DENY"


class DenialStage(str, Enum):
    COMMITTEE = "COMMITTEE"
    BOARD = "BOARD"


class EvaluationStage(str, Enum):
    PLANNING = "PLANNING"
    GOALS_SET = "GOALS_SET"
    MIDYEAR_REVIEW = "MIDYEAR_REVIEW"
    SUMMATIVE_DRAFT = "SUMMATIVE_DRAFT"
    ADOPTED = "ADOPTED"


class EvaluationAction(str, Enum):
    SET_GOALS = "SET_GOALS"
    MIDYEAR = "MIDYEAR"
    DRAFT_SUMMATIVE = "DRAFT_SUMMATIVE"
    REOPEN = "REOPEN"
    ADOPT = "ADOPT"


class RubricDomain(str, Enum):
    INSTRUCTIONAL_LEADERSHIP = "INSTRUCTIONAL_LEADERSHIP"
    FISCAL_STEWARDSHIP = "FISCAL_STEWARDSHIP"
    COMMUNITY_RELATIONS = "COMMUNITY_RELATIONS"
    GOVERNANCE_SUPPORT = "GOVERNANCE_SUPPORT"


class RatingPhase(str, Enum):
    FORMATIVE = "FORMATIVE"
    SUMMATIVE = "SUMMATIVE"


class PublicationStatus(str, Enum):
    BUILDING = "BUILDING"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class CertificationState(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    LAPSED = "LAPSED"


# ---------------------------------------------------------------------------
# Entity shapes. Every resource family carries id, created_at, updated_at and
# version, as the requirements state without exception.
# ---------------------------------------------------------------------------


class BoardMember(TypedDict):
    id: str
    full_name: str
    seat_number: int
    office: str
    term_start_date: str
    term_end_date: str
    employer_name: str
    status: str
    open_recusal_count: int
    active_committee_count: int
    created_at: str
    updated_at: str
    version: int


class Committee(TypedDict):
    id: str
    name: str
    charter_type: str
    seat_capacity: int
    quorum_size: int
    status: str
    filled_seat_count: int
    voting_seat_count: int
    vacant_seat_count: int
    created_at: str
    updated_at: str
    version: int


class CommitteeAssignment(TypedDict):
    id: str
    committee_id: str
    board_member_id: str
    role_on_committee: str
    status: str
    assigned_on: str
    removed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConflictDisclosure(TypedDict):
    id: str
    board_member_id: str
    policy_id: str
    nature: str
    narrative: str
    status: str
    disclosed_on: str
    cleared_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    code: str
    title: str
    category: str
    legal_requirement_level: str
    manual_section: str
    status: str
    adopted_version_no: Optional[int]
    last_review_date: Optional[str]
    version_count: int
    open_mandate_count: int
    overdue_mandate_count: int
    active_waiver_count: int
    compliance_state: str
    created_at: str
    updated_at: str
    version: int


class PolicyVersion(TypedDict):
    id: str
    policy_id: str
    version_no: int
    body_text: str
    summary_of_change: str
    status: str
    reading_count: int
    first_reading_meeting_id: Optional[str]
    adopting_meeting_id: Optional[str]
    adopted_at: Optional[str]
    effective_date: Optional[str]
    superseded_at: Optional[str]
    withdrawn_reason: Optional[str]
    policy_version_after: int
    created_at: str
    updated_at: str
    version: int


class LegalMandate(TypedDict):
    id: str
    notice_code: str
    policy_id: str
    citation: str
    issued_on: str
    compliance_deadline: str
    required_action: str
    status: str
    satisfied_by_version_no: Optional[int]
    days_past_deadline: int
    created_at: str
    updated_at: str
    version: int


class Meeting(TypedDict):
    id: str
    title: str
    scope: str
    committee_id: Optional[str]
    meeting_type: str
    scheduled_start_utc: str
    public_comment_rule: str
    status: str
    minutes_status: str
    minutes_approved_at_meeting_id: Optional[str]
    notice_posted_at: Optional[str]
    agenda_locked_at: Optional[str]
    opened_at: Optional[str]
    adjourned_at: Optional[str]
    seated_member_count_snapshot: int
    attending_member_ids: List[str]
    quorum_required: int
    public_comment_minutes_budget: int
    public_comment_minutes_remaining: int
    public_comment_allocation_variant: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgendaItem(TypedDict):
    id: str
    meeting_id: str
    sequence_no: int
    item_type: str
    title: str
    policy_version_id: Optional[str]
    waiver_request_id: Optional[str]
    requires_public_comment: bool
    status: str
    vote_yes: int
    vote_no: int
    vote_abstain: int
    recused_member_count: int
    absent_member_count: int
    required_yes_votes: Optional[int]
    vote_outcome: Optional[str]
    acted_at: Optional[str]
    meeting_version_after: int
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict):
    id: str
    agenda_item_id: str
    speaker_name: str
    speaker_affiliation: str
    requested_minutes: int
    submitted_at: str
    allotted_minutes: int
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaiverRequest(TypedDict):
    id: str
    policy_id: str
    reviewing_committee_id: str
    requesting_school_code: str
    justification: str
    requested_start_date: str
    requested_end_date: str
    status: str
    committee_recommendation: Optional[str]
    denial_stage: Optional[str]
    max_allowed_days: int
    granted_start_date: Optional[str]
    granted_end_date: Optional[str]
    granted_days: int
    revoked_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SuperintendentEvaluation(TypedDict):
    id: str
    cycle_year: int
    window_start_date: str
    window_end_date: str
    midyear_checkpoint_date: str
    goal_count: int
    weight_instructional: float
    weight_fiscal: float
    weight_community: float
    weight_governance: float
    status: str
    reopen_count: int
    rating_count: int
    eligible_rater_count: int
    midyear_formative_score: Optional[float]
    summative_composite_score: Optional[float]
    adopted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvaluationRating(TypedDict):
    id: str
    evaluation_id: str
    board_member_id: str
    domain: str
    score: int
    comments: Optional[str]
    submitted_at: str
    phase: str
    counted_in_summative: bool
    created_at: str
    updated_at: str
    version: int


class ManualPublication(TypedDict):
    id: str
    publication_label: str
    as_of_date: str
    status: str
    certification_state: str
    pinned_entries: List[Dict[str, Any]]
    entry_count: int
    compliance_gap_count: int
    published_at: Optional[str]
    superseded_by_label: Optional[str]
    created_at: str
    updated_at: str
    version: int
