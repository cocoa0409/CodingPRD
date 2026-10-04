"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COMMISSION_ADMIN = "CommissionAdmin"
    COMMISSION_STAFF = "CommissionStaff"
    INSTITUTION_LIAISON = "InstitutionLiaison"
    PEER_REVIEWER = "PeerReviewer"


class LegalStatus(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE_NONPROFIT = "PRIVATE_NONPROFIT"
    PRIVATE_FORPROFIT = "PRIVATE_FORPROFIT"


class DegreeLevel(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    BACCALAUREATE = "BACCALAUREATE"
    MASTERS = "MASTERS"
    DOCTORAL = "DOCTORAL"


class AccreditationStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    CANDIDATE = "CANDIDATE"
    ACCREDITED = "ACCREDITED"
    DENIED_ENTRY = "DENIED_ENTRY"
    WITHDRAWN = "WITHDRAWN"


class SanctionStatus(str, Enum):
    NONE = "NONE"
    NOTICE = "NOTICE"
    PROBATION = "PROBATION"
    SHOW_CAUSE = "SHOW_CAUSE"
    MEMBERSHIP_REMOVED = "MEMBERSHIP_REMOVED"


class CandidacyPathway(str, Enum):
    STANDARD = "STANDARD"
    ACCELERATED = "ACCELERATED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    DEFICIENT = "DEFICIENT"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AdjudicationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    REQUEST_COMPLETION = "REQUEST_COMPLETION"


class CycleType(str, Enum):
    INITIAL_ACCREDITATION = "INITIAL_ACCREDITATION"
    REAFFIRMATION = "REAFFIRMATION"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MATERIALS_OPEN = "MATERIALS_OPEN"
    EVALUATION_ACTIVE = "EVALUATION_ACTIVE"
    VISIT_COMPLETE = "VISIT_COMPLETE"
    PANEL_REVIEW = "PANEL_REVIEW"
    DECIDED = "DECIDED"
    CLOSED = "CLOSED"


class FederalComplianceStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"


class ComponentResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ArgumentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    REVIEW_LOCKED = "REVIEW_LOCKED"
    ACCEPTED = "ACCEPTED"
    REJECTED_AS_INSUFFICIENT = "REJECTED_AS_INSUFFICIENT"


class CriterionCode(str, Enum):
    MISSION = "CRIT_MISSION"
    INTEGRITY = "CRIT_INTEGRITY"
    TEACHING_QUALITY = "CRIT_TEACHING_QUALITY"
    TEACHING_EVALUATION = "CRIT_TEACHING_EVALUATION"
    RESOURCES_PLANNING = "CRIT_RESOURCES_PLANNING"


class EvidenceType(str, Enum):
    INSTITUTIONAL_DATA = "INSTITUTIONAL_DATA"
    ASSESSMENT_RESULT = "ASSESSMENT_RESULT"
    FINANCIAL_INDICATOR = "FINANCIAL_INDICATOR"
    POLICY_DOCUMENT = "POLICY_DOCUMENT"


class VisitModality(str, Enum):
    ON_SITE = "ON_SITE"
    VIRTUAL = "VIRTUAL"


class TeamStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    VISIT_SCHEDULED = "VISIT_SCHEDULED"
    REPORT_FILED = "REPORT_FILED"
    DISBANDED = "DISBANDED"


class TeamRole(str, Enum):
    CHAIR = "CHAIR"
    MEMBER = "MEMBER"


class ConflictStatus(str, Enum):
    CLEARED = "CLEARED"
    CONFLICTED = "CONFLICTED"


class AssignmentResponse(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class PanelStatus(str, Enum):
    CONVENED = "CONVENED"
    CLOSED = "CLOSED"


class VoteChoice(str, Enum):
    REAFFIRM = "REAFFIRM"
    GRANT = "GRANT"
    NOTICE = "NOTICE"
    PROBATION = "PROBATION"
    SHOW_CAUSE = "SHOW_CAUSE"
    DENY = "DENY"
    WITHDRAW = "WITHDRAW"


class CriterionRating(str, Enum):
    MET = "MET"
    MET_WITH_CONCERNS = "MET_WITH_CONCERNS"
    NOT_MET = "NOT_MET"


class OutcomeOrigin(str, Enum):
    PANEL = "PANEL"
    INDICATOR_MONITOR = "INDICATOR_MONITOR"


class ActionType(str, Enum):
    REAFFIRMATION = "REAFFIRMATION"
    GRANT_INITIAL = "GRANT_INITIAL"
    DENIAL = "DENIAL"
    NOTICE = "NOTICE"
    PROBATION = "PROBATION"
    SHOW_CAUSE = "SHOW_CAUSE"
    WITHDRAWAL = "WITHDRAWAL"


class OutcomeStatus(str, Enum):
    DRAFTED = "DRAFTED"
    DISCLOSED = "DISCLOSED"
    EFFECTIVE = "EFFECTIVE"


class CureStatus(str, Enum):
    NONE = "NONE"
    UNDER_CURE_REVIEW = "UNDER_CURE_REVIEW"
    CURED = "CURED"


class SanctionAction(str, Enum):
    OPEN_CURE_REVIEW = "OPEN_CURE_REVIEW"
    CURE = "CURE"
    ESCALATE = "ESCALATE"


class ChangeType(str, Enum):
    NEW_LOCATION = "NEW_LOCATION"
    PROGRAM_LEVEL = "PROGRAM_LEVEL"
    OWNERSHIP_CHANGE = "OWNERSHIP_CHANGE"
    DISTANCE_DELIVERY = "DISTANCE_DELIVERY"


class ChangeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DEFERRED = "DEFERRED"


class ChangeDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    DEFER = "DEFER"


class ReportStatus(str, Enum):
    DUE = "DUE"
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    FLAGGED_REVIEW = "FLAGGED_REVIEW"
    FLAGGED_PANEL = "FLAGGED_PANEL"


class CfiVariant(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class CfiBand(str, Enum):
    CLEAR = "CLEAR"
    REVIEW = "REVIEW"
    PANEL = "PANEL"


# --- Entity TypedDicts (all twelve resources carry id/created_at/updated_at/version) ---

class Institution(TypedDict):
    id: str
    legal_name: str
    legal_status: str
    state_code: str
    fte_enrollment: int
    degree_levels_offered: List[str]
    distance_delivery_approved: bool
    locations_count: int
    accreditation_status: str
    sanction_status: str
    candidacy_pathway: Optional[str]
    candidacy_started_at: Optional[str]
    candidacy_expires_at: Optional[str]
    accredited_since: Optional[str]
    last_reaffirmed_at: Optional[str]
    current_annual_dues_cents: int
    dues_paid_cents: int
    outstanding_dues_cents: int
    latest_cfi_value: Optional[float]
    latest_cfi_band: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityApplication(TypedDict):
    id: str
    institution_id: str
    pathway: str
    statement_of_intent: str
    status: str
    filed_at: Optional[str]
    adjudicated_at: Optional[str]
    adjudication_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewCycle(TypedDict):
    id: str
    institution_id: str
    cycle_type: str
    status: str
    federal_compliance_status: str
    federal_components: List[dict]
    cohort_default_rates: List[float]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssuranceArgument(TypedDict):
    id: str
    review_cycle_id: str
    narrative_text: str
    status: str
    revision_count: int
    readiness_self_reported: Optional[float]
    readiness_team_verified: Optional[float]
    submitted_at: Optional[str]
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict):
    id: str
    assurance_argument_id: str
    criterion_code: str
    evidence_type: str
    title: str
    document_uri: str
    verified: bool
    verified_by_reviewer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict):
    id: str
    full_name: str
    affiliation_institution_id: Optional[str]
    specialty_criteria: List[str]
    declared_conflict_institution_ids: List[str]
    quality_rating: float
    prior_chair_count: int
    is_active: bool
    current_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class ReviewTeam(TypedDict):
    id: str
    review_cycle_id: str
    visit_modality: str
    status: str
    chair_reviewer_id: str
    visit_start_at: Optional[str]
    visit_end_at: Optional[str]
    criterion_ratings: List[dict]
    report_recommendation: Optional[str]
    report_summary: Optional[str]
    recommended_action_computed: Optional[str]
    report_filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TeamAssignment(TypedDict):
    id: str
    review_team_id: str
    reviewer_id: str
    role_on_team: str
    conflict_status: str
    response: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DecisionPanel(TypedDict):
    id: str
    review_cycle_id: str
    member_reviewer_ids: List[str]
    status: str
    votes: List[dict]
    prevailing_action: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActionOutcome(TypedDict):
    id: str
    review_cycle_id: Optional[str]
    indicator_origin_institution_id: Optional[str]
    origin: str
    action_type: str
    status: str
    public_disclosure_text: Optional[str]
    disclosed_at: Optional[str]
    effective_at: Optional[str]
    sanction_level: Optional[str]
    cure_status: str
    cure_review_opened_at: Optional[str]
    cure_threshold_snapshot: Optional[int]
    cure_deadline_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstantiveChangeRequest(TypedDict):
    id: str
    institution_id: str
    change_type: str
    requested_program_level: Optional[str]
    new_location_state: Optional[str]
    ownership_details: Optional[str]
    status: str
    decision_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IndicatorReport(TypedDict):
    id: str
    institution_id: str
    period_start: str
    period_end: str
    status: str
    primary_reserve_ratio: Optional[float]
    viability_ratio: Optional[float]
    net_operating_ratio: Optional[float]
    state_appropriation_ratio: Optional[float]
    enrollment_change_pct: Optional[float]
    completion_rate: Optional[float]
    retention_rate: Optional[float]
    fte_enrollment: Optional[int]
    cfi_value: Optional[float]
    cfi_variant_used: Optional[str]
    emi_value: Optional[float]
    evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
