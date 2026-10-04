"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the common system-managed fields (id, created_at,
updated_at, version) described in PRD section on common resource properties.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD roles section)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PROGRAM_OFFICER = "ProgramOfficer"
    REFERRAL_OFFICER = "ReferralOfficer"
    SCIENTIFIC_REVIEW_OFFICER = "ScientificReviewOfficer"
    REVIEWER = "Reviewer"
    COUNCIL_MEMBER = "CouncilMember"
    GRANTS_OFFICER = "GrantsOfficer"
    APPLICANT = "Applicant"


# ---------------------------------------------------------------------------
# Field enums
# ---------------------------------------------------------------------------

class ActivityCode(str, Enum):
    R01 = "R01"
    R21 = "R21"
    R03 = "R03"


class CareerStage(str, Enum):
    NEW_INVESTIGATOR = "NEW_INVESTIGATOR"
    EARLY_STAGE_INVESTIGATOR = "EARLY_STAGE_INVESTIGATOR"
    ESTABLISHED_INVESTIGATOR = "ESTABLISHED_INVESTIGATOR"


class FoaStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REFERRED = "REFERRED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SCORED = "SCORED"
    UNSCORED = "UNSCORED"
    DEFERRED = "DEFERRED"
    COUNCIL_REVIEWED = "COUNCIL_REVIEWED"
    JIT_PENDING = "JIT_PENDING"
    JIT_COMPLETE = "JIT_COMPLETE"
    AWARDED = "AWARDED"
    NOT_FUNDED = "NOT_FUNDED"
    WITHDRAWN = "WITHDRAWN"


class StudySectionStatus(str, Enum):
    RECRUITING = "RECRUITING"
    MEETING_HELD = "MEETING_HELD"
    SCORES_RELEASED = "SCORES_RELEASED"


class ReviewerStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"


class AssignmentRole(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CRITIQUE_SUBMITTED = "CRITIQUE_SUBMITTED"
    CANCELLED = "CANCELLED"


class CouncilRecommendation(str, Enum):
    FUND = "FUND"
    DEFER = "DEFER"
    NOT_FUND = "NOT_FUND"


class JitItem(str, Enum):
    OTHER_SUPPORT = "OTHER_SUPPORT"
    BUDGET_JUSTIFICATION = "BUDGET_JUSTIFICATION"
    IRB_APPROVAL = "IRB_APPROVAL"
    IACUC_APPROVAL = "IACUC_APPROVAL"


class JitStatus(str, Enum):
    ISSUED = "ISSUED"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


class AwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRANSFERRED = "TRANSFERRED"
    TERMINATED = "TERMINATED"


class AwardTerm(str, Enum):
    STANDARD_TERMS_V1 = "STANDARD_TERMS_V1"
    RESTRICTED_DRAW_DOWN = "RESTRICTED_DRAW_DOWN"
    TRANSFERRED_AWARD = "TRANSFERRED_AWARD"


class ProgressReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class AwardModificationType(str, Enum):
    CARRYOVER = "CARRYOVER"
    NO_COST_EXTENSION = "NO_COST_EXTENSION"
    TERMINATION = "TERMINATION"


class AwardModificationStatus(str, Enum):
    AUTO_APPROVED = "AUTO_APPROVED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class TransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RELINQUISHED = "RELINQUISHED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class ProrationVariant(str, Enum):
    TIME_PRORATED = "TIME_PRORATED"
    LEDGER_ACTUALS = "LEDGER_ACTUALS"


class RespondDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class JitAdjudicateDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class ModificationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class TransferDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------

class FundingOpportunity(TypedDict, total=False):
    id: str
    pa_number: str
    title: str
    activity_code: str
    research_strategy_page_limit: int
    min_direct_cents_per_year: int
    max_direct_cents_per_year: int
    max_years: int
    open_date: str
    receipt_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Institute(TypedDict, total=False):
    id: str
    name: str
    appropriation_cents: int
    reserve_cents: int
    indirect_cost_rate: float
    select_pay_cap_pct: float
    select_pay_extension_percentile: float
    committed_cents: int
    disbursed_cents: int
    select_pay_spent_cents: int
    current_payline_percentile: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Institution(TypedDict, total=False):
    id: str
    name: str
    human_subjects_certification_expiry: Optional[str]
    animal_welfare_assurance_expiry: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    career_stage: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    foa_id: str
    applicant_id: str
    institution_id: str
    title: str
    research_strategy_page_count: int
    direct_cents_per_year: List[int]
    requested_years: int
    human_subjects_involved: bool
    vertebrate_animals_involved: bool
    requested_study_section_id: Optional[str]
    requested_institute_id: Optional[str]
    excluded_reviewer_ids: List[str]
    study_section_id: Optional[str]
    institute_id: Optional[str]
    live_assignment_count: int
    impact_score: Optional[int]
    approach_mean: Optional[float]
    significance_mean: Optional[float]
    innovation_mean: Optional[float]
    percentile_raw: Optional[float]
    percentile_normalized: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class StudySection(TypedDict, total=False):
    id: str
    name: str
    meeting_date: str
    application_quota: int
    assigned_application_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict, total=False):
    id: str
    full_name: str
    institution_id: str
    expertise_keywords: List[str]
    declared_conflicts: List[str]
    active_assignment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    application_id: str
    reviewer_id: str
    role: str
    significance_score: Optional[int]
    innovation_score: Optional[int]
    approach_score: Optional[int]
    investigator_score: Optional[int]
    environment_score: Optional[int]
    overall_impact_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CouncilReview(TypedDict, total=False):
    id: str
    application_id: str
    recommendation: str
    priority_alignment_score: Optional[int]
    portfolio_balance_note: Optional[str]
    recorded_by: str
    created_at: str
    updated_at: str
    version: int


class JitRequest(TypedDict, total=False):
    id: str
    application_id: str
    required_items: List[str]
    submitted_items: List[str]
    due_date: str
    budget_cut_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    application_id: str
    institute_id: str
    institution_id: str
    start_date: str
    end_date: str
    period_total_cents: List[int]
    total_awarded_cents: int
    disbursed_cents: int
    disbursed_per_period_cents: List[int]
    carried_out_per_period_cents: List[int]
    current_period: int
    terms_and_conditions: List[str]
    originating_transfer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgressReport(TypedDict, total=False):
    id: str
    award_id: str
    period_year: int
    actual_expenditure_cents: int
    publications_count: int
    submitted_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AwardModification(TypedDict, total=False):
    id: str
    award_id: str
    type: str
    amount_cents: Optional[int]
    from_period: Optional[int]
    new_end_date: Optional[str]
    reason: Optional[str]
    auto_approved: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict, total=False):
    id: str
    award_id: str
    to_institution_id: str
    effective_date: str
    proration_variant: Optional[str]
    relinquished_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
