"""Domain types: status enums, entity TypedDicts and the role enum.

Shapes follow the PRD contract: most resources carry the full common shape
(id, created_at, updated_at, version), while the append-only artifacts
(ConflictScreening, CommitteeVote, RatingActionEvent) carry only id and
created_at.
"""
from enum import Enum
from typing import TypedDict


class Role(str, Enum):
    ENGAGEMENT_MANAGER = "EngagementManager"
    RATING_ANALYST = "RatingAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    COMMITTEE_CHAIR = "CommitteeChair"
    COMPENSATION_COMMITTEE = "CompensationCommittee"
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"


class Sector(str, Enum):
    CORPORATE_FINANCE = "CORPORATE_FINANCE"
    FINANCIAL_INSTITUTIONS = "FINANCIAL_INSTITUTIONS"
    SOVEREIGN = "SOVEREIGN"
    STRUCTURED_FINANCE = "STRUCTURED_FINANCE"
    PROJECT_FINANCE = "PROJECT_FINANCE"


class RevenueBand(str, Enum):
    LARGE = "LARGE"
    MID = "MID"
    SMALL = "SMALL"


class SolicitationStatus(str, Enum):
    SOLICITED = "SOLICITED"
    UNSOLICITED = "UNSOLICITED"


class SurveillancePosture(str, Enum):
    NORMAL = "NORMAL"
    ACTIVE_WATCH = "ACTIVE_WATCH"
    RESTRICTED = "RESTRICTED"


class EngagementLetterStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class RatingRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    TEAM_CONFIRMED = "TEAM_CONFIRMED"
    COMMITTEE_DECIDED = "COMMITTEE_DECIDED"
    APPEALED = "APPEALED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class AnalystTier(str, Enum):
    LEAD = "LEAD"
    SUPPORT = "SUPPORT"
    COMMITTEE_ELIGIBLE = "COMMITTEE_ELIGIBLE"


class TeamAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SCREENED = "SCREENED"
    CONFIRMED = "CONFIRMED"
    REVOKED = "REVOKED"


class ConflictStatus(str, Enum):
    PENDING_SCREEN = "PENDING_SCREEN"
    CLEAR = "CLEAR"
    POTENTIAL = "POTENTIAL"
    DISQUALIFYING = "DISQUALIFYING"


class CommitteeStatus(str, Enum):
    CONVENED = "CONVENED"
    IN_SESSION = "IN_SESSION"
    DECIDED = "DECIDED"
    DISSOLVED = "DISSOLVED"
    QUORUM_FAILED = "QUORUM_FAILED"


class DecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    APPEAL_WINDOW = "APPEAL_WINDOW"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class MethodologyStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class CompensationStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"


GRADE_SCALE = ["AAA", "AA", "A", "BAA", "BA", "B", "CAA", "CA", "C"]
GRADE_STEP = {grade: index for index, grade in enumerate(GRADE_SCALE)}


# ─── full common shape (id + created_at + updated_at + version) ───

class Methodology(TypedDict):
    id: str
    name: str
    version_code: str
    methodology_code: str
    sector: str
    is_public: bool
    effective_from: str
    effective_to: str | None
    status: str
    created_at: str
    updated_at: str
    version: int


class RatedEntity(TypedDict):
    id: str
    legal_name: str
    sector: str
    domicile_country: str
    revenue_band: str
    methodology_id: str
    solicitation_status: str
    surveillance_posture: str
    first_rated_at: str | None
    current_grade: str | None
    created_at: str
    updated_at: str
    version: int


class EngagementLetter(TypedDict):
    id: str
    rated_entity_id: str
    fee_amount_cents: int
    fee_structure: str
    fee_payer_is_issuer: bool
    signed_at: str
    cooling_off_end_at: str | None
    fee_credited_cents: int
    fee_reversed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RatingRequest(TypedDict):
    id: str
    engagement_letter_id: str
    rated_entity_id: str
    instrument_type: str
    instrument_notional_cents: int
    requested_rating_scale: str
    received_at: str
    allocated_fee_cents: int
    request_status: str
    created_at: str
    updated_at: str
    version: int


class Analyst(TypedDict):
    id: str
    full_name: str
    primary_sector: str
    analyst_tier: str
    independence_declared_at: str
    first_assignment_at: str | None
    last_lead_assignment_at: str | None
    consecutive_lead_months: int
    rotation_eligible: bool
    is_departed: bool
    departed_to_entity_id: str | None
    created_at: str
    updated_at: str
    version: int


class AnalyticalTeamAssignment(TypedDict):
    id: str
    rating_request_id: str
    lead_analyst_id: str
    support_analyst_id: str
    assigned_at: str
    window_start: str
    window_end: str
    conflict_status: str
    rotation_exemption_granted: bool
    rotation_exemption_reason: str | None
    status: str
    created_at: str
    updated_at: str
    version: int


class RatingCommittee(TypedDict):
    id: str
    rating_request_id: str
    committee_date: str
    required_voting_members: int
    votes_cast: int
    quorum_met: bool
    dissent_count: int
    committee_status: str
    created_at: str
    updated_at: str
    version: int


class RatingDecision(TypedDict):
    id: str
    rating_request_id: str
    assigned_grade: str
    prior_grade: str | None
    outlook: str
    watch_status: str
    rationale: str
    dissent_count: int
    dissent_score: float
    decision_status: str
    published_at: str | None
    appeal_window_end_at: str | None
    is_unsolicited: bool
    methodology_code: str
    created_at: str
    updated_at: str
    version: int


class IssuerAppeal(TypedDict):
    id: str
    rating_decision_id: str
    filer_user_id: str
    new_information_summary: str
    contains_new_information: bool
    appeal_outcome: str | None
    submitted_at: str
    resolution_notes: str | None
    created_at: str
    updated_at: str
    version: int


class SurveillanceReview(TypedDict):
    id: str
    rated_entity_id: str
    rating_decision_id: str | None
    review_type: str
    review_cycle_months: int
    review_due_at: str
    overdue_days: int
    escalation_index: int
    review_status: str
    created_at: str
    updated_at: str
    version: int


class AppearanceReconciliation(TypedDict):
    id: str
    analyst_id: str
    rating_decision_id: str
    stated_role: str
    evidence_reference: str
    confirmed_at: str | None
    reconciliation_status: str
    created_at: str
    updated_at: str
    version: int


class ReviewSlot(TypedDict):
    id: str
    analyst_id: str
    surveillance_review_id: str
    slot_start: str
    slot_end: str
    pre_buffer_minutes: int
    post_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AnalystCompensation(TypedDict):
    id: str
    analyst_id: str
    base_salary_cents: int
    compensation_separation_pct: float
    fee_generation_bonus_cents: int
    rating_accuracy_score: float
    accuracy_bonus_cents: int
    comp_period: str
    total_compensation_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LookBackReview(TypedDict):
    id: str
    analyst_id: str
    departed_to_entity_id: str
    departure_date: str
    lookback_period_months: int
    affected_decisions_count: int
    review_status: str
    created_at: str
    updated_at: str
    version: int


# ─── append-only shape (id + created_at only) ───

class ConflictScreening(TypedDict):
    id: str
    team_assignment_id: str
    analyst_id: str
    conflict_type: str
    screening_result: str
    reviewer_user_id: str
    screened_at: str
    created_at: str


class CommitteeVote(TypedDict):
    id: str
    rating_committee_id: str
    analyst_id: str
    vote_value: str
    assigned_grade: str | None
    dissent_rationale: str | None
    is_dissent: bool
    voted_at: str
    created_at: str


class RatingActionEvent(TypedDict):
    id: str
    surveillance_review_id: str
    rating_decision_id: str
    event_type: str
    target_grade: str | None
    effective_at: str
    event_status: str
    applied_at: str | None
    created_at: str