"""Domain types for the Charity Accountability Rating API.

Status enums, role enum and entity TypedDicts, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    RATING_ANALYST = "RatingAnalyst"
    PUBLISHING_REVIEWER = "PublishingReviewer"
    APPEAL_PANELIST = "AppealPanelist"
    METHODOLOGY_ADMIN = "MethodologyAdmin"
    ORGANIZATION_REP = "OrganizationRep"
    PUBLIC_USER = "PublicUser"


class OrgType(str, Enum):
    PUBLIC_CHARITY = "PUBLIC_CHARITY"
    PRIVATE_FOUNDATION = "PRIVATE_FOUNDATION"
    RELIGIOUS_CONGREGATION = "RELIGIOUS_CONGREGATION"
    DONOR_ADVISED_SPONSOR = "DONOR_ADVISED_SPONSOR"
    MEMBERSHIP_ASSOCIATION = "MEMBERSHIP_ASSOCIATION"


class TrendDirection(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    IMPROVED = "IMPROVED"
    UNCHANGED = "UNCHANGED"
    DECLINED = "DECLINED"


class ChangeDirection(str, Enum):
    FIRST_PUBLICATION = "FIRST_PUBLICATION"
    IMPROVED = "IMPROVED"
    UNCHANGED = "UNCHANGED"
    DECLINED = "DECLINED"


class Grade(str, Enum):
    ACCREDITED = "ACCREDITED"
    MEETS_STANDARDS = "MEETS_STANDARDS"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    DOES_NOT_MEET = "DOES_NOT_MEET"
    UNRATED = "UNRATED"


class MethodologyStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMENT_OPEN = "COMMENT_OPEN"
    COMMENT_CLOSED = "COMMENT_CLOSED"
    ADOPTED = "ADOPTED"
    RETIRED = "RETIRED"


class PublicCommentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INCORPORATED = "INCORPORATED"
    DECLINED = "DECLINED"


class CommenterKind(str, Enum):
    DONOR = "DONOR"
    RATED_ORGANIZATION = "RATED_ORGANIZATION"
    PUBLIC = "PUBLIC"


class TransitionGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class TriggerReason(str, Enum):
    WEIGHT_CHANGE = "WEIGHT_CHANGE"
    THRESHOLD_TIGHTENED = "THRESHOLD_TIGHTENED"


class FilingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SourceKind(str, Enum):
    AUDITED_STATEMENT = "AUDITED_STATEMENT"
    PUBLIC_FILING = "PUBLIC_FILING"
    ORG_SUBMISSION = "ORG_SUBMISSION"


class FilingOrigin(str, Enum):
    ORG_PORTAL = "ORG_PORTAL"
    ANALYST_ENTRY = "ANALYST_ENTRY"
    CORRECTION_APPLIED = "CORRECTION_APPLIED"


class GovernanceEvaluationStatus(str, Enum):
    PENDING = "PENDING"
    EVALUATED = "EVALUATED"


class StandardCode(str, Enum):
    AUDIT_COMMITTEE = "AUDIT_COMMITTEE"
    BOARD_INDEPENDENCE = "BOARD_INDEPENDENCE"
    BOARD_MEETING_FREQUENCY = "BOARD_MEETING_FREQUENCY"
    BOARD_SIZE_MIN = "BOARD_SIZE_MIN"
    CEO_COMP_REVIEW = "CEO_COMP_REVIEW"
    COI_POLICY = "COI_POLICY"
    COI_POLICY_CURRENCY = "COI_POLICY_CURRENCY"
    WHISTLEBLOWER_POLICY = "WHISTLEBLOWER_POLICY"


class StandardResult(str, Enum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    WAIVED = "WAIVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CycleStatus(str, Enum):
    DATA_COLLECTION = "DATA_COLLECTION"
    SCORED = "SCORED"
    ORG_REVIEW = "ORG_REVIEW"
    CORRECTION_REQUESTED = "CORRECTION_REQUESTED"
    APPEAL_OPEN = "APPEAL_OPEN"
    APPEAL_RESOLVED = "APPEAL_RESOLVED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class Dimension(str, Enum):
    FINANCIAL_HEALTH = "FINANCIAL_HEALTH"
    ACCOUNTABILITY = "ACCOUNTABILITY"
    TRANSPARENCY = "TRANSPARENCY"
    IMPACT = "IMPACT"


class DimensionStatus(str, Enum):
    PENDING = "PENDING"
    COMPUTED = "COMPUTED"
    OVERRIDDEN = "OVERRIDDEN"
    STALE = "STALE"


class CorrectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_ANALYST_REVIEW = "UNDER_ANALYST_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CorrectionTargetKind(str, Enum):
    FILING_FINANCIAL = "FILING_FINANCIAL"
    GOVERNANCE_DISCLOSURE = "GOVERNANCE_DISCLOSURE"


class AppealStatus(str, Enum):
    FILED = "FILED"
    PANEL_ASSIGNED = "PANEL_ASSIGNED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    DISMISSED = "DISMISSED"


class ComplaintStatus(str, Enum):
    INTAKE = "INTAKE"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    REFERRED_OUT = "REFERRED_OUT"


class ComplainantKind(str, Enum):
    DONOR = "DONOR"
    BENEFICIARY = "BENEFICIARY"
    EMPLOYEE = "EMPLOYEE"
    ANONYMOUS = "ANONYMOUS"


class ComplaintCategory(str, Enum):
    MISUSE_OF_FUNDS = "MISUSE_OF_FUNDS"
    GOVERNANCE = "GOVERNANCE"
    SOLICITATION_PRACTICE = "SOLICITATION_PRACTICE"
    TRANSPARENCY = "TRANSPARENCY"
    OTHER = "OTHER"


class CredibilityVariant(str, Enum):
    INTAKE = "INTAKE"
    INVESTIGATED = "INVESTIGATED"


class SeverityTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RecipientKind(str, Enum):
    RATED_ORGANIZATION = "RATED_ORGANIZATION"
    MEDIA = "MEDIA"


# ── Entities carrying id + created_at + updated_at + version ──────────────


class Organization(TypedDict):
    id: str
    legal_name: str
    ein: str
    org_type: str
    fiscal_year_end_month: int
    contact_email: str
    latest_published_score: Optional[float]
    latest_published_grade: Optional[str]
    published_cycle_count: int
    trend_direction: str
    transition_grace_until: Optional[str]
    substantiated_complaint_count: int
    created_at: str
    updated_at: str
    version: int


class MethodologyVersion(TypedDict):
    id: str
    version_label: str
    status: str
    weight_financial_health: float
    weight_accountability: float
    weight_transparency: float
    weight_impact: float
    dimension_floor_score: float
    comment_period_days: int
    transition_period_days: int
    supersedes_version_id: Optional[str]
    revision_note: Optional[str]
    comment_count: int
    unresolved_comment_count: int
    comment_open_at: Optional[str]
    comment_deadline_at: Optional[str]
    comment_closed_at: Optional[str]
    adopted_at: Optional[str]
    retired_at: Optional[str]
    effective_from: Optional[str]
    effective_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict):
    id: str
    methodology_version_id: str
    commenter_kind: str
    commenter_user_id: str
    body: str
    status: str
    disposition_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransitionGrant(TypedDict):
    id: str
    organization_id: str
    methodology_version_id: str
    superseded_version_label: str
    status: str
    grace_until: str
    projected_score_delta: float
    trigger_reason: str
    created_at: str
    updated_at: str
    version: int


class FilingRecord(TypedDict):
    id: str
    organization_id: str
    fiscal_year: int
    source_kind: str
    source_precedence: int
    origin: str
    status: str
    total_expense_cents: int
    program_expense_cents: int
    fundraising_expense_cents: int
    admin_expense_cents: int
    contributions_cents: int
    total_revenue_cents: int
    net_assets_cents: int
    total_liabilities_cents: int
    grants_paid_cents: int
    membership_services_cents: int
    joint_cost_allocated_cents: int
    validated_at: Optional[str]
    rejection_code: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GovernanceProfile(TypedDict):
    id: str
    rating_cycle_id: str
    board_member_count: int
    independent_board_member_count: int
    conflict_of_interest_policy_on_file: bool
    coi_policy_reviewed_at: Optional[str]
    board_meetings_last_year: int
    audit_committee_exists: bool
    whistleblower_policy: bool
    ceo_compensation_reviewed: bool
    impact_report_on_file: bool
    outcome_measures_count: int
    third_party_evaluation_on_file: bool
    evaluation_status: str
    independence_ratio: Optional[float]
    evaluated_at: Optional[str]
    standards_met_count: int
    standards_not_met_count: int
    standards_waived_count: int
    standards_not_applicable_count: int
    created_at: str
    updated_at: str
    version: int


class StandardEvaluation(TypedDict):
    id: str
    governance_profile_id: str
    standard_code: str
    result: str
    observed_value: str
    required_value: str
    evaluated_at: str
    waiver_reason: Optional[str]
    waived_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RatingCycle(TypedDict):
    id: str
    organization_id: str
    methodology_version_id: str
    methodology_pin_locked: bool
    fiscal_year: int
    period_start: str
    period_end: str
    status: str
    assigned_analyst_user_id: str
    publishing_reviewer_user_id: Optional[str]
    review_opened_at: Optional[str]
    correction_deadline_at: Optional[str]
    appeal_deadline_at: Optional[str]
    published_at: Optional[str]
    correction_round: int
    program_expense_ratio: Optional[float]
    fundraising_efficiency: Optional[float]
    months_of_reserve: Optional[float]
    data_completeness_pct: Optional[float]
    failed_standard_count: int
    accountability_penalty_points: int
    standards_penalty_points: Optional[float]
    weighted_sum_provisional: Optional[float]
    provisional_composite_score: Optional[float]
    provisional_grade: Optional[str]
    weighted_sum_final: Optional[float]
    final_composite_score: Optional[float]
    grade: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DimensionScore(TypedDict):
    id: str
    rating_cycle_id: str
    dimension: str
    raw_points: int
    max_points: int
    normalized_score: float
    weight_applied: float
    weighted_contribution: float
    data_completeness_pct: float
    penalty_points: int
    status: str
    override_reason: Optional[str]
    overridden_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectionRequest(TypedDict):
    id: str
    rating_cycle_id: str
    target_kind: str
    target_fiscal_year: Optional[int]
    target_source_kind: Optional[str]
    target_field_name: str
    proposed_value: str
    narrative: str
    status: str
    round_number: int
    submitted_by_org_user_id: str
    claimed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    rating_cycle_id: str
    correction_request_id: str
    grounds: str
    status: str
    filed_by_org_user_id: str
    filed_at: str
    deadline_at: Optional[str]
    panel_member_user_ids: List[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    organization_id: str
    complainant_kind: str
    complainant_user_id: str
    category: str
    narrative: str
    corroborating_document_count: int
    status: str
    credibility_score: Optional[float]
    credibility_variant: Optional[str]
    severity_tier: Optional[str]
    investigation_due_at: Optional[str]
    penalty_points_applied: int
    penalized_rating_cycle_id: Optional[str]
    triage_note: Optional[str]
    referred_to: Optional[str]
    finding_note: Optional[str]
    reversal_reason: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ── Append-only entity: id + created_at only, no updated_at, no version ───


class PublicationRecord(TypedDict):
    id: str
    rating_cycle_id: str
    organization_id: str
    sequence_number: int
    published_score: float
    published_grade: str
    weighted_sum_final: float
    standards_penalty_points: float
    methodology_version_label: str
    published_at: str
    previous_published_score: Optional[float]
    score_delta: Optional[float]
    change_direction: str
    notified_recipient_kinds: List[str]
    created_at: str
