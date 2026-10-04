"""Domain types: entity TypedDicts, status enums and the role enum.

Every resource in this API carries the complete quartet of `id`, `created_at`,
`updated_at` and `version`, so every entity TypedDict below lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    MASTER_POLICY_ADMIN = "MasterPolicyAdmin"
    UNDERWRITER = "Underwriter"
    LENDER = "Lender"
    SERVICER = "Servicer"
    BORROWER = "Borrower"


class CoverageApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_UNDERWRITING = "IN_UNDERWRITING"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING_CANCELLATION = "PENDING_CANCELLATION"
    CANCELLED = "CANCELLED"


class AmortizationStatus(str, Enum):
    IN_AMORTIZATION = "IN_AMORTIZATION"
    AT_78 = "AT_78"
    AT_80 = "AT_80"


class TerminationReason(str, Enum):
    NONE = "NONE"
    BORROWER_REQUEST = "BORROWER_REQUEST"
    LTV_MILESTONE = "LTV_MILESTONE"
    SERVICER_LOSS_MITIGATION_FAILURE = "SERVICER_LOSS_MITIGATION_FAILURE"


class RescissionReliefStatus(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    GUARANTEED = "GUARANTEED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"
    RESCINDED = "RESCINDED"


class PremiumPlan(str, Enum):
    BPM = "BPM"
    SPM = "SPM"
    LPM = "LPM"


class LtvBand(str, Enum):
    BAND_831_85 = "831_TO_85"
    BAND_851_90 = "851_TO_90"
    BAND_901_95 = "901_TO_95"


class MasterPolicy(TypedDict):
    id: str
    policy_number: str
    anniversary_utc: str
    coverage_percent_default: int
    delegated_curtailment_rate: float
    nondelagated_curtailment_rate: float
    ltv_variance_tolerance: float
    servicer_loss_mitigation_standard: str
    rescission_relief_cycles: int
    min_third_party_net_bps: int
    two_year_effective_flag: bool
    exposure_contribution_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    master_policy_id: str
    credit_grade: str
    ltv_band: str
    coverage_percent: int
    premium_plan: str
    rate_bps: int
    min_borrower_reserves_months: int
    created_at: str
    updated_at: str
    version: int


class ReinsuranceTreaty(TypedDict):
    id: str
    treaty_number: str
    inception_utc: str
    expiration_utc: str
    retention_per_claim_cents: int
    exhaustion_per_claim_cents: int
    aggregate_ceded_cap_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Servicer(TypedDict):
    id: str
    servicer_name: str
    tier: str
    loss_mitigation_capability: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lender(TypedDict):
    id: str
    lender_name: str
    delegated_underwriting: bool
    policy_exposure_cap_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoverageApplication(TypedDict):
    id: str
    lender_id: str
    master_policy_id: str
    rate_card_id: str
    borrower_reference: str
    loan_amount_cents: int
    property_value_cents: int
    credit_grade: str
    coverage_percent: int
    premium_plan: str
    borrower_paid: bool
    financed_premium: bool
    borrower_reserves_months: int
    county_code: str
    term_months: int
    underwriting_path: str
    submitted_utc: str
    underwritten_utc: Optional[str]
    resubmission_count: int
    approved_coverage_percent: int
    rate_bps_applied: int
    coverage_base_upb_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    application_id: str
    servicer_id: str
    reinsurance_treaty_id: Optional[str]
    lender_id: str
    master_policy_id: str
    coverage_percent: int
    premium_plan: str
    borrower_paid: bool
    underwriting_path: str
    rate_bps_applied: int
    coverage_base_upb_cents: int
    current_upb_cents: int
    current_coverage_base_cents: int
    annual_premium_cents: int
    monthly_period_cents: int
    final_period_cents: int
    single_premium_cents: int
    origination_property_value_cents: int
    verified_property_value_cents: Optional[int]
    verified_loan_amount_cents: Optional[int]
    credit_grade: str
    county_code: str
    term_months: int
    approval_credit_grade: str
    coverage_status: str
    termination_reason: str
    cancellation_effective_utc: Optional[str]
    amortization_status: str
    milestone_78_reached_utc: Optional[str]
    delinquency_streak: int
    last_loss_mitigation_deficient_utc: Optional[str]
    rescission_relief_status: str
    rescission_relief_cycle_index: int
    claim_blocked: bool
    aggregate_ceded_cents: int
    created_at: str
    updated_at: str
    version: int


class DelinquencyReport(TypedDict):
    id: str
    loan_id: str
    servicer_id: str
    as_of_period: str
    delinquency_class: str
    months_delinquent: int
    loss_mitigation_activities: List[dict]
    reported_utc: str
    effective_utc: str
    participation_standard_met: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CancellationNotice(TypedDict):
    id: str
    loan_id: str
    request_kind: str
    requested_by_role: str
    notice_utc: str
    evidence_cents: int
    applied_utc: str
    refund_cents: int
    effective_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExternalReport(TypedDict):
    id: str
    loan_id: str
    verified_loan_amount_cents: int
    verified_property_value_cents: int
    post_origination_value_cents: int
    occupancy_reported: str
    independent_validation_completed_utc: str
    validated_ltv: float
    occupancy_materially_differs: bool
    created_at: str
    updated_at: str
    version: int


class CurtailmentDispute(TypedDict):
    id: str
    loan_id: str
    lender_id: str
    target_claim_id: str
    grounds: str
    asserted_coverage_percent: int
    filed_utc: str
    decision: Optional[str]
    decision_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    loan_id: str
    event_kind: str
    event_completed_utc: str
    unpaid_principal_cents: int
    accrued_interest_cents: int
    allowable_advances_cents: int
    gross_proceeds_cents: int
    expenses_of_sale_cents: int
    filed_utc: str
    curtailment_rate_applied: Optional[float]
    permitted_interest_cents: Optional[int]
    permitted_advances_cents: Optional[int]
    net_unpaid_balance_cents: Optional[int]
    recoverable_amount_cents: Optional[int]
    coverage_ceiling_cents: Optional[int]
    covered_claim_amount_cents: Optional[int]
    post_curtailment_cents: Optional[int]
    claim_deductible_cents: Optional[int]
    net_claim_amount_cents: Optional[int]
    trace_number: str
    settlement_option_kind: Optional[str]
    settlement_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimSettlementOption(TypedDict):
    id: str
    claim_id: str
    option_kind: str
    computed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class PortfolioSnapshot(TypedDict):
    id: str
    snapshot_utc: str
    cluster_in_force_threshold_cents: int
    lender_concentration_index: Optional[float]
    geography_totals: List[dict]
    aggregate_ceded_cents: int
    segment_statuses: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReinsuranceCession(TypedDict):
    id: str
    claim_id: str
    loan_id: str
    treaty_id: Optional[str]
    ceded_amount_cents: int
    retained_amount_cents: int
    aggregate_ceded_after_cents: int
    status: str
    rejected_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int