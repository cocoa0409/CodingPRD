"""Domain types for the Academic Integrity Case Adjudication API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles (PRD §2.1 — exactly six, spelled exactly as follows)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    INTEGRITY_OFFICER = "IntegrityOfficer"
    FACULTY_REPORTER = "FacultyReporter"
    PANEL_CHAIR = "PanelChair"
    STUDENT = "Student"
    APPEALS_DEAN = "AppealsDean"
    REGISTRAR_OFFICER = "RegistrarOfficer"


ALL_ROLES = [r.value for r in UserRole]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MonitoringFlag(str, Enum):
    NORMAL = "NORMAL"
    TRAINING_DEFICIT = "TRAINING_DEFICIT"
    UNDER_REPORTING = "UNDER_REPORTING"
    ELEVATED = "ELEVATED"


class TrainingStatus(str, Enum):
    LAPSED = "LAPSED"
    CURRENT = "CURRENT"


class StudentStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class TranscriptNotation(str, Enum):
    NONE = "NONE"
    POSTED = "POSTED"
    EXPUNGED = "EXPUNGED"


class ViolationType(str, Enum):
    PLAGIARISM = "PLAGIARISM"
    UNAUTHORIZED_COLLABORATION = "UNAUTHORIZED_COLLABORATION"
    EXAM_CHEATING = "EXAM_CHEATING"
    FABRICATION_OF_DATA = "FABRICATION_OF_DATA"
    CONTRACT_CHEATING = "CONTRACT_CHEATING"
    FACILITATION = "FACILITATION"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    ACCEPTED = "ACCEPTED"
    REJECTED_INSUFFICIENT = "REJECTED_INSUFFICIENT"


class TriageDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN_FOR_INFO = "RETURN_FOR_INFO"
    REJECT_INSUFFICIENT = "REJECT_INSUFFICIENT"


class EvidenceKind(str, Enum):
    SIMILARITY_REPORT = "SIMILARITY_REPORT"
    PROCTOR_LOG = "PROCTOR_LOG"
    WITNESS_STATEMENT = "WITNESS_STATEMENT"
    DOCUMENT = "DOCUMENT"


class CaseOrigin(str, Enum):
    OFFICE_INTAKE = "OFFICE_INTAKE"
    LEGACY_IMPORT = "LEGACY_IMPORT"


class CasePathway(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    INFORMAL = "INFORMAL"
    FORMAL = "FORMAL"


class AdjudicationStatus(str, Enum):
    INTAKE_REVIEW = "INTAKE_REVIEW"
    NOTIFIED = "NOTIFIED"
    INFORMAL_PROPOSED = "INFORMAL_PROPOSED"
    INFORMAL_ACCEPTED = "INFORMAL_ACCEPTED"
    FORMAL_REFERRED = "FORMAL_REFERRED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    HEARING_IN_PROGRESS = "HEARING_IN_PROGRESS"
    DECIDED = "DECIDED"
    APPEAL_UNDER_REVIEW = "APPEAL_UNDER_REVIEW"
    SANCTION_IMPOSED = "SANCTION_IMPOSED"
    CLOSED = "CLOSED"
    DISMISSED = "DISMISSED"


class NotationStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_POSTING = "PENDING_POSTING"
    POSTED = "POSTED"
    EXPUNGEMENT_REQUESTED = "EXPUNGEMENT_REQUESTED"
    EXPUNGED = "EXPUNGED"
    EXPUNGEMENT_DENIED = "EXPUNGEMENT_DENIED"


class ResponsibilityFinding(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    RESPONSIBLE = "RESPONSIBLE"
    NOT_RESPONSIBLE = "NOT_RESPONSIBLE"


class FindingBasis(str, Enum):
    NONE = "NONE"
    ADMISSION = "ADMISSION"
    PANEL = "PANEL"
    APPEAL = "APPEAL"
    LEGACY = "LEGACY"


class NotificationKind(str, Enum):
    ALLEGATION_NOTICE = "ALLEGATION_NOTICE"
    MEETING_NOTICE = "MEETING_NOTICE"
    HEARING_NOTICE = "HEARING_NOTICE"
    REHEARING_NOTICE = "REHEARING_NOTICE"
    SANCTION_NOTICE = "SANCTION_NOTICE"
    SANCTION_RECOMPUTE_NOTICE = "SANCTION_RECOMPUTE_NOTICE"
    APPEAL_OUTCOME_NOTICE = "APPEAL_OUTCOME_NOTICE"


class AdvisorKind(str, Enum):
    FACULTY_ADVISOR = "FACULTY_ADVISOR"
    STUDENT_PEER = "STUDENT_PEER"
    ATTORNEY = "ATTORNEY"


class AdvisorEngagementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class MeetingOutcome(str, Enum):
    HELD = "HELD"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONVENED = "CONVENED"
    DECIDED = "DECIDED"
    ADJOURNED = "ADJOURNED"
    CANCELLED = "CANCELLED"


class Verdict(str, Enum):
    RESPONSIBLE = "RESPONSIBLE"
    NOT_RESPONSIBLE = "NOT_RESPONSIBLE"
    ABSTAIN = "ABSTAIN"


class SanctionKind(str, Enum):
    WARNING = "WARNING"
    GRADE_PENALTY_ASSIGNMENT = "GRADE_PENALTY_ASSIGNMENT"
    GRADE_PENALTY_COURSE = "GRADE_PENALTY_COURSE"
    TRANSCRIPT_NOTATION_ONLY = "TRANSCRIPT_NOTATION_ONLY"
    DISCIPLINARY_PROBATION = "DISCIPLINARY_PROBATION"
    SUSPENSION_ONE_TERM = "SUSPENSION_ONE_TERM"
    SUSPENSION_ONE_YEAR = "SUSPENSION_ONE_YEAR"
    EXPULSION_RECOMMENDATION = "EXPULSION_RECOMMENDATION"


class SanctionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"
    IMPOSED = "IMPOSED"
    VACATED = "VACATED"
    COMPLETED = "COMPLETED"


class SanctionOrigin(str, Enum):
    OFFICE_PROPOSAL = "OFFICE_PROPOSAL"
    INFORMAL_PROPOSAL = "INFORMAL_PROPOSAL"
    APPEAL_REDUCTION = "APPEAL_REDUCTION"


class VacatedReason(str, Enum):
    APPEAL_OVERTURNED = "APPEAL_OVERTURNED"
    APPEAL_REMANDED = "APPEAL_REMANDED"
    APPEAL_REDUCED = "APPEAL_REDUCED"
    CASE_DISMISSED = "CASE_DISMISSED"
    SUPERSEDED_BY_NEWER_PROPOSAL = "SUPERSEDED_BY_NEWER_PROPOSAL"
    LADDER_RECOMPUTE = "LADDER_RECOMPUTE"


class AppealGrounds(str, Enum):
    PROCEDURE = "PROCEDURE"
    EVIDENCE = "EVIDENCE"
    SANCTION_SEVERITY = "SANCTION_SEVERITY"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DENIED_NO_GROUNDS = "DENIED_NO_GROUNDS"
    UPHELD_ORIGINAL = "UPHELD_ORIGINAL"
    SANCTION_REDUCED = "SANCTION_REDUCED"
    REMANDED = "REMANDED"
    OVERTURNED = "OVERTURNED"


class AppealScreenDecision(str, Enum):
    ACCEPT_FOR_REVIEW = "ACCEPT_FOR_REVIEW"
    DENY_NO_GROUNDS = "DENY_NO_GROUNDS"


class AppealOutcome(str, Enum):
    UPHELD_ORIGINAL = "UPHELD_ORIGINAL"
    SANCTION_REDUCED = "SANCTION_REDUCED"
    REMANDED = "REMANDED"
    OVERTURNED = "OVERTURNED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class InformalResponse(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class ExpungementDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class ReportingBasis(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"


class PathwayBasis(str, Enum):
    FORMAL = "FORMAL"
    INFORMAL = "INFORMAL"


# ---------------------------------------------------------------------------
# Entity shapes
#
# Thirteen of the fifteen resource types carry id / created_at / updated_at /
# version.  EvidenceItem and PanelVote are immutable and carry ONLY id and
# created_at — their TypedDicts deliberately omit updated_at and version.
# ---------------------------------------------------------------------------


class Department(TypedDict):
    id: str
    code: str
    name: str
    enrolled_student_count: int
    faculty_headcount: int
    open_case_count: int
    training_completion_pct: float
    reporting_rate_per_1k_submitted: float
    monitoring_flag: str
    created_at: str
    updated_at: str
    version: int


class FacultyMember(TypedDict):
    id: str
    department_id: str
    full_name: str
    email: str
    training_status: str
    training_completed_at: Optional[str]
    training_module_code: Optional[str]
    reports_submitted_count: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    email: str
    program_code: str
    class_year: int
    prior_upheld_count: int
    active_sanction_points: int
    standing: str
    transcript_notation: str
    created_at: str
    updated_at: str
    version: int


class GradeComponent(TypedDict):
    code: str
    max_points: int
    weight_pct: int


class ComponentScore(TypedDict):
    code: str
    earned_points: int


class CourseOffering(TypedDict):
    id: str
    department_id: str
    instructor_id: str
    course_code: str
    term_code: str
    grade_components: List[GradeComponent]
    created_at: str
    updated_at: str
    version: int


class IntegrityReport(TypedDict):
    id: str
    offering_id: str
    student_id: str
    reporter_id: str
    alleged_violation_type: str
    narrative: str
    incident_at: str
    component_scores: List[ComponentScore]
    submitted_at: Optional[str]
    status: str
    evidence_strength_score: float
    evidence_complete: bool
    returned_at: Optional[str]
    triaged_at: Optional[str]
    resubmission_count: int
    triage_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict):
    """Immutable exhibit — carries only id and created_at (PRD §2.5)."""

    id: str
    report_id: str
    kind: str
    sha256: str
    page_count: int
    similarity_pct: Optional[float]
    created_at: str


class Case(TypedDict):
    id: str
    report_id: Optional[str]
    student_id: str
    offering_id: str
    case_number: str
    origin: str
    pathway: str
    adjudication_status: str
    notation_status: str
    responsibility_finding: str
    finding_basis: str
    hearing_round: int
    overturned: bool
    decided_at: Optional[str]
    evidence_strength_score: float
    baseline_course_grade_pct: float
    cross_course_pattern_points: int
    prior_upheld_count_at_assessment: int
    prior_escalation_points: int
    provisional_severity_index: float
    severity_index: float
    recommended_ladder_rank: int
    informal_severity_index: float
    informal_recommended_ladder_rank: int
    panel_severity_recommendation: Optional[int]
    pre_appeal_adjudication_status: Optional[str]
    dismiss_reason: Optional[str]
    expungement_eligible_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Notification(TypedDict):
    id: str
    case_id: str
    kind: str
    response_window_days: int
    sent_at: str
    response_deadline_at: str
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdvisorEngagement(TypedDict):
    id: str
    case_id: str
    advisor_full_name: str
    advisor_kind: str
    advisor_bar_licensed: bool
    status: str
    speaking_rights: bool
    reconfirmation_required: bool
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseMeeting(TypedDict):
    id: str
    case_id: str
    instructor_id: str
    start_at: str
    end_at: str
    duration_minutes: int
    status: str
    advisor_present: bool
    created_at: str
    updated_at: str
    version: int


class HearingRoom(TypedDict):
    id: str
    code: str
    seat_capacity: int
    buffer_minutes: int
    sessions_per_day_cap: int
    booked_minutes_total: int
    created_at: str
    updated_at: str
    version: int


class HearingSession(TypedDict):
    id: str
    case_id: str
    room_id: str
    chair_id: str
    panelist_ids: List[str]
    required_panel_size: int
    start_at: str
    end_at: str
    status: str
    round_number: int
    effective_vote_count: int
    quorum_required: int
    panel_finding: Optional[str]
    panel_severity_recommendation: Optional[int]
    adjourn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PanelVote(TypedDict):
    """Immutable recorded ballot — carries only id and created_at (PRD §2.5)."""

    id: str
    session_id: str
    panelist_id: str
    verdict: str
    severity_recommendation: Optional[int]
    cast_at: str
    created_at: str


class Sanction(TypedDict):
    id: str
    case_id: str
    replaces_sanction_id: Optional[str]
    kind: str
    ladder_rank: int
    grade_component_code: Optional[str]
    effective_from: str
    status: str
    origin: str
    baseline_course_grade_pct: float
    adjusted_course_grade_pct: float
    grade_penalty_delta_pct: float
    imposed_at: Optional[str]
    completed_at: Optional[str]
    vacated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    case_id: str
    grounds: str
    statement: str
    filed_at: str
    status: str
    hearing_round_at_filing: int
    reduced_ladder_rank: Optional[int]
    decision_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
