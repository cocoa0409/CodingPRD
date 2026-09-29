"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    UNDERWRITING_OFFICER = "UnderwritingOfficer"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    CLAIMS_COMMITTEE_APPROVER = "ClaimsCommitteeApprover"
    PEER_REVIEW_CHAIR = "PeerReviewChair"
    ACTUARIAL_ANALYST = "ActuarialAnalyst"
    CHIEF_ACTUARY = "ChiefActuary"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    INSURED = "Insured"


class InsuredStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CredentialingStatus(str, Enum):
    PENDING = "PENDING"
    PROVISIONAL = "PROVISIONAL"
    CREDENTIALED = "CREDENTIALED"
    LAPSED = "LAPSED"
    DENIED = "DENIED"


class RiskClassCode(str, Enum):
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class PeerReviewStatus(str, Enum):
    REFERRED = "REFERRED"
    IN_REVIEW = "IN_REVIEW"
    REVIEWS_COMPLETE = "REVIEWS_COMPLETE"
    CLOSED = "CLOSED"


class ReviewOutcome(str, Enum):
    NO_CONCERN = "NO_CONCERN"
    CONCERN = "CONCERN"
    INDETERMINATE = "INDETERMINATE"


class CommitteeVoteResult(str, Enum):
    NO_DEVIATION = "NO_DEVIATION"
    DEVIATION_MINOR = "DEVIATION_MINOR"
    DEVIATION_MAJOR = "DEVIATION_MAJOR"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CoverageForm(str, Enum):
    CLAIMS_MADE = "CLAIMS_MADE"
    OCCURRENCE = "OCCURRENCE"


class ConsentClause(str, Enum):
    ABSOLUTE = "ABSOLUTE"
    HAMMER = "HAMMER"
    NONE = "NONE"


class PolicyTermStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    IN_FORCE = "IN_FORCE"
    EXPIRED = "EXPIRED"
    CANCELLED_FLAT = "CANCELLED_FLAT"
    CANCELLED_PRO_RATA = "CANCELLED_PRO_RATA"


class RatingVariant(str, Enum):
    UNDERWRITING_SNAPSHOT = "UNDERWRITING_SNAPSHOT"
    RENEWAL_PROSPECTIVE = "RENEWAL_PROSPECTIVE"


class TailType(str, Enum):
    ERP_5YR = "ERP_5YR"
    ERP_UNLIMITED = "ERP_UNLIMITED"
    DEATH_DISABILITY_RETIREMENT = "DEATH_DISABILITY_RETIREMENT"


class TailStatus(str, Enum):
    QUOTED = "QUOTED"
    ISSUED = "ISSUED"
    VOID = "VOID"


class ClaimStatus(str, Enum):
    INTAKE = "INTAKE"
    INVESTIGATION = "INVESTIGATION"
    LITIGATION = "LITIGATION"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class CoverageStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    COVERED = "COVERED"
    RESERVED_RIGHTS = "RESERVED_RIGHTS"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    PRIOR_ACTS_EXCLUDED = "PRIOR_ACTS_EXCLUDED"
    NO_RESPONDING_COVERAGE = "NO_RESPONDING_COVERAGE"
    TERM_VOIDED = "TERM_VOIDED"
    ADJUSTER_DENIAL = "ADJUSTER_DENIAL"


class SeverityBand(str, Enum):
    BAND_1 = "BAND_1"
    BAND_2 = "BAND_2"
    BAND_3 = "BAND_3"
    BAND_4 = "BAND_4"


class Disposition(str, Enum):
    DEFENSE_VERDICT = "DEFENSE_VERDICT"
    PLAINTIFF_VERDICT = "PLAINTIFF_VERDICT"
    SETTLED = "SETTLED"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class ReserveMethod(str, Enum):
    CASE_BASIS = "CASE_BASIS"
    FORMULA_BASIS = "FORMULA_BASIS"


class PanelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    REMOVED = "REMOVED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    DECLINED = "DECLINED"
    REPLACED = "REPLACED"
    CLOSED = "CLOSED"


class DeclineReason(str, Enum):
    CONFLICT_OF_INTEREST = "CONFLICT_OF_INTEREST"
    CAPACITY = "CAPACITY"
    RATE_DISPUTE = "RATE_DISPUTE"
    EXPERTISE_MISMATCH = "EXPERTISE_MISMATCH"


class NegotiationStatus(str, Enum):
    AUTHORITY_REQUESTED = "AUTHORITY_REQUESTED"
    AUTHORITY_GRANTED = "AUTHORITY_GRANTED"
    AUTHORITY_DENIED = "AUTHORITY_DENIED"
    CONSENT_REQUESTED = "CONSENT_REQUESTED"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    VETOED = "VETOED"
    HAMMER_INVOKED = "HAMMER_INVOKED"
    PAID = "PAID"
    ABANDONED = "ABANDONED"


class PhysicianResponse(str, Enum):
    CONSENTED = "CONSENTED"
    VETOED = "VETOED"


class NpdbReportStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VOID = "VOID"


class NonReportableReason(str, Enum):
    NON_PRACTITIONER_PAYMENT = "NON_PRACTITIONER_PAYMENT"
    ZERO_DOLLAR_RESOLUTION = "ZERO_DOLLAR_RESOLUTION"


class RateFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AdequacyFlag(str, Enum):
    DEFICIENT = "DEFICIENT"
    ADEQUATE = "ADEQUATE"
    REDUNDANT = "REDUNDANT"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class IndicationMethod(str, Enum):
    LOSS_RATIO_METHOD = "LOSS_RATIO_METHOD"
    PURE_PREMIUM_METHOD = "PURE_PREMIUM_METHOD"


# --- Entity shapes ---------------------------------------------------------
# Records that carry the full audit block expose id, created_at, updated_at
# and version. Reserve postings are the single append-only exception and
# expose only id and created_at.


class SpecialtyClass(TypedDict):
    id: str
    specialty_code: str
    base_class_code: str
    base_rate_per_million: float
    hazard_index: float
    benchmark_severity: float
    rate_revision_index: int
    last_approved_rate_change_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Insured(TypedDict):
    id: str
    entity_type: str
    legal_name: str
    specialty_class_id: str
    venue_code: str
    high_severity_procedure_pct: float
    years_in_practice: int
    board_certified: bool
    status: str
    credentialing_status: str
    credentialing_expires_on: Optional[str]
    risk_class_score: float
    risk_class_code: str
    risk_class_factor: float
    surcharge_pct: float
    closed_paid_claim_count: int
    open_claim_count: int
    npdb_reported_payment_total: float
    created_at: str
    updated_at: str
    version: int


class RiskProgramEnrollment(TypedDict):
    id: str
    insured_id: str
    program_code: str
    enrolled_on: str
    completed_on: Optional[str]
    attestation_reference: Optional[str]
    credit_pct_snapshot: float
    expires_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PeerReviewCase(TypedDict):
    id: str
    insured_id: str
    trigger_source: str
    referral_note: str
    status: str
    chart_review_outcome: Optional[str]
    external_review_outcome: Optional[str]
    committee_vote_result: Optional[str]
    votes_for: Optional[int]
    votes_against: Optional[int]
    surcharge_pct_assigned: float
    closed_on: Optional[str]
    chair_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    insured_id: str
    policy_number: str
    coverage_form: str
    limit_per_claim: float
    limit_aggregate: float
    retroactive_date: Optional[str]
    prior_acts_step_credit: int
    consent_to_settle_clause: str
    status: str
    current_term_id: Optional[str]
    quoted_premium_total: float
    written_premium_net_total: float
    created_at: str
    updated_at: str
    version: int


class PolicyTerm(TypedDict):
    id: str
    policy_id: str
    predecessor_term_id: Optional[str]
    term_index: int
    effective_date: str
    expiration_date: str
    claims_made_step_year: int
    step_factor: float
    rating_variant: str
    rated_risk_class_code: str
    rated_risk_class_factor: float
    venue_severity_factor: float
    increased_limits_factor: float
    credit_pct_applied: float
    surcharge_pct_applied: float
    premium_manual: float
    premium_net: float
    administrative_fee: float
    guaranty_fund_assessment: float
    term_total: float
    return_premium: float
    aggregate_limit_remaining: float
    rate_revision_index_used: int
    status: str
    cancel_effective_date: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TailEndorsement(TypedDict):
    id: str
    policy_id: str
    triggering_term_id: str
    tail_type: str
    trigger_reason: str
    effective_date: str
    reporting_window_end: str
    mature_premium_basis: float
    tail_factor: float
    tail_premium: float
    status: str
    issued_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    insured_id: str
    policy_term_id: Optional[str]
    tail_endorsement_id: Optional[str]
    incident_date: str
    report_date: str
    venue_code: str
    allegation_category: str
    demand_amount: float
    claim_status: str
    coverage_status: str
    denial_reason: Optional[str]
    reserved_rights_reason: Optional[str]
    severity_band: str
    severity_band_factor: float
    indemnity_reserve: float
    expense_reserve: float
    reserve_method_current: Optional[str]
    paid_indemnity: float
    paid_expense: float
    case_incurred: float
    actuarial_incurred: float
    insured_share_receivable: float
    disposition: Optional[str]
    verdict_amount: Optional[float]
    suit_filed_on: Optional[str]
    resolved_on: Optional[str]
    closed_on: Optional[str]
    counsel_reassignment_required: bool
    excluded_counsel_firm_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class ReserveEntry(TypedDict):
    """Append-only accounting document: only id and created_at are carried."""

    id: str
    claim_id: str
    method: str
    indemnity_amount: Optional[float]
    expense_amount: Optional[float]
    computed_indemnity_amount: float
    computed_expense_amount: float
    effective_at: str
    rationale: str
    set_by_user_id: str
    created_at: str


class DefenseCounselFirm(TypedDict):
    id: str
    firm_name: str
    admitted_venue_codes: List[str]
    allegation_specialties: List[str]
    blended_hourly_rate: float
    quality_score: int
    max_concurrent_assignments: int
    conflict_insured_ids: List[str]
    panel_status: str
    open_assignment_count: int
    billed_expense_total: float
    panel_status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CounselAssignment(TypedDict):
    id: str
    claim_id: str
    counsel_firm_id: str
    assignment_status: str
    assigned_at: str
    selection_rank_snapshot: int
    candidate_pool_size: int
    decline_reason: Optional[str]
    billed_expense_amount: float
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementNegotiation(TypedDict):
    id: str
    claim_id: str
    round_index: int
    proposed_amount: float
    authority_requested: float
    authority_granted: Optional[float]
    status: str
    physician_response: Optional[str]
    veto_reason: Optional[str]
    consent_requested_at: Optional[str]
    consent_clause_applied: str
    hammer_invoked: bool
    hammer_exposure_estimate: float
    insured_share_amount: float
    carrier_share_amount: float
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    paid_amount: Optional[float]
    payment_date: Optional[str]
    notice_sent_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NPDBReport(TypedDict):
    id: str
    claim_id: str
    settlement_negotiation_id: Optional[str]
    insured_id: str
    payment_amount: float
    payment_date: str
    reportable: bool
    non_reportable_reason: Optional[str]
    due_date: str
    report_status: str
    submitted_on: Optional[str]
    submitted_late: bool
    days_late: int
    submitter_note: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateFiling(TypedDict):
    id: str
    specialty_class_id: str
    filing_number: str
    indication_method: str
    proposed_rate_change_pct: float
    experience_period_start: str
    experience_period_end: str
    effective_date: str
    claim_count_in_scope: int
    in_scope_premium_total: float
    actuarial_incurred_total: float
    experience_loss_ratio: Optional[float]
    indicated_change_pct: Optional[float]
    credibility_weight: float
    credibility_weighted_indication_pct: Optional[float]
    carried_reserve_total: float
    required_reserve_total: float
    reserve_adequacy_ratio: Optional[float]
    adequacy_flag: str
    status: str
    prepared_by_user_id: str
    decided_by_user_id: Optional[str]
    approved_rate_change_pct: Optional[float]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
