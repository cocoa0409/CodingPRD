"""Domain types: status enumerations and entity shapes.

Nine primary resources carry `id`, `created_at`, `updated_at` and `version`.
Four record types are append-only observations and carry only `id` and
`created_at`: census tracts, eligibility tests, annual compliance tests and
job reports.  Their TypedDicts deliberately omit `updated_at` and `version`.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CERTIFYING_AGENCY = "CertifyingAgency"
    CDE_SPONSOR = "CDESponsor"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    TAX_CREDIT_INVESTOR = "TaxCreditInvestor"
    QALICB_SPONSOR = "QALICBSponsor"


class CdeCertificationStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    DECERTIFIED = "DECERTIFIED"


class ServiceAreaScope(str, Enum):
    NATIONAL = "NATIONAL"
    MULTI_STATE = "MULTI_STATE"
    STATEWIDE = "STATEWIDE"
    LOCAL = "LOCAL"


class AwardLifecycleStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    ACTIVE = "ACTIVE"
    COMPLIANCE_PERIOD_CLOSED = "COMPLIANCE_PERIOD_CLOSED"
    TERMINATED = "TERMINATED"


class CompliancePosture(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class SubstantiallyAllMethod(str, Enum):
    DIRECT_TRACING = "DIRECT_TRACING"
    AGGREGATE_BALANCE = "AGGREGATE_BALANCE"


class DistressTier(str, Enum):
    INELIGIBLE = "INELIGIBLE"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class QalicbEligibilityStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    RECERTIFICATION_DUE = "RECERTIFICATION_DUE"
    FAILED = "FAILED"
    DISQUALIFIED = "DISQUALIFIED"


class EligibilityTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class EligibilityProng(str, Enum):
    LOCATION = "LOCATION"
    GROSS_INCOME = "GROSS_INCOME"
    SERVICES = "SERVICES"
    TANGIBLE_PROPERTY = "TANGIBLE_PROPERTY"
    COLLECTIBLES = "COLLECTIBLES"
    NQFP = "NQFP"


class InvestmentFundStatus(str, Enum):
    FORMED = "FORMED"
    FUNDED = "FUNDED"
    QEI_MADE = "QEI_MADE"
    WOUND_UP = "WOUND_UP"


class QeiDeploymentStatus(str, Enum):
    ISSUED = "ISSUED"
    DEPLOYING = "DEPLOYING"
    FULLY_DEPLOYED = "FULLY_DEPLOYED"
    REINVESTMENT_PENDING = "REINVESTMENT_PENDING"
    UNWOUND = "UNWOUND"
    VOIDED = "VOIDED"


class QeiComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    RECAPTURED = "RECAPTURED"
    RELEASED = "RELEASED"


class RecaptureTriggerType(str, Enum):
    NONE = "NONE"
    SUBSTANTIALLY_ALL_FAILURE = "SUBSTANTIALLY_ALL_FAILURE"
    CDE_DECERTIFICATION = "CDE_DECERTIFICATION"
    REINVESTMENT_BREACH = "REINVESTMENT_BREACH"


class QliciStatus(str, Enum):
    DEPLOYED = "DEPLOYED"
    PARTIALLY_REPAID = "PARTIALLY_REPAID"
    REPAID = "REPAID"
    NON_QUALIFYING = "NON_QUALIFYING"


class ReinvestmentObligationStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    BREACHED = "BREACHED"


class CbaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CURE_REQUIRED = "CURE_REQUIRED"
    BREACHED = "BREACHED"
    CLOSED = "CLOSED"


class MeasurementBasis(str, Enum):
    HEADCOUNT = "HEADCOUNT"
    PAYROLL_HOURS = "PAYROLL_HOURS"


class CertificationClassification(str, Enum):
    CERTIFIED = "CERTIFIED"
    CURE_REQUIRED = "CURE_REQUIRED"
    SHORTFALL = "SHORTFALL"


class UnwindStatus(str, Enum):
    OPTION_WINDOW_OPEN = "OPTION_WINDOW_OPEN"
    PUT_EXERCISED = "PUT_EXERCISED"
    CALL_EXERCISED = "CALL_EXERCISED"
    SETTLED = "SETTLED"
    EXPIRED = "EXPIRED"


class OptionType(str, Enum):
    PUT = "PUT"
    CALL = "CALL"


# --- Primary resources: id + created_at + updated_at + version --------------


class Cde(TypedDict):
    id: str
    legal_name: str
    certification_number: str
    service_area_scope: str
    certification_status: str
    decertified_at: Optional[str]
    decertification_reason: Optional[str]
    award_count: int
    created_at: str
    updated_at: str
    version: int


class AllocationAward(TypedDict):
    id: str
    cde_id: str
    award_year: int
    allocation_amount_cents: int
    service_area_state_codes: List[str]
    min_severe_distress_share_pct: float
    substantially_all_method: str
    lifecycle_status: str
    compliance_posture: str
    remaining_authority_cents: int
    issued_qei_count: int
    at_risk_qei_count: int
    recaptured_qei_count: int
    cba_breach_count: int
    severe_distress_share_pct: float
    last_agency_report_year: Optional[int]
    allocation_agreement_signed_at: Optional[str]
    signatory_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Qalicb(TypedDict):
    id: str
    census_tract_id: str
    legal_name: str
    state_code: str
    naics_code: str
    sponsor_user_id: str
    eligibility_status: str
    last_certified_at: Optional[str]
    latest_test_result: Optional[str]
    consecutive_failed_test_count: int
    funding_qlici_count: int
    created_at: str
    updated_at: str
    version: int


class InvestmentFund(TypedDict):
    id: str
    legal_name: str
    equity_contribution_cents: int
    leverage_lender_name: str
    leverage_loan_principal_cents: int
    leverage_loan_rate_bps: int
    investor_user_id: str
    status: str
    equity_received_cents: int
    leverage_received_cents: int
    leverage_loan_outstanding_cents: int
    capital_available_cents: int
    deployed_to_qei_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Qei(TypedDict):
    id: str
    allocation_award_id: str
    investment_fund_id: str
    qei_amount_cents: int
    reserve_bps: int
    permitted_fees_cents: int
    net_deployable_cents: int
    uninvested_cash_cents: int
    issued_at: str
    issued_by_user_id: str
    deployment_deadline_at: str
    deployment_status: str
    compliance_status: str
    compliance_years_completed: int
    substantially_all_pct_direct: float
    substantially_all_pct_aggregate: float
    accrued_unpaid_fee_cents: int
    recapture_trigger_type: str
    recapture_exposure_cents: int
    cure_deadline_at: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Qlici(TypedDict):
    id: str
    qei_id: str
    qalicb_id: str
    loan_class: str
    principal_cents: int
    deployed_at: str
    status: str
    outstanding_principal_cents: int
    total_repaid_cents: int
    allocated_fee_cents: int
    non_qualifying_since_at: Optional[str]
    created_by_cure: bool
    created_at: str
    updated_at: str
    version: int


class ReinvestmentObligation(TypedDict):
    id: str
    qei_id: str
    source_qlici_id: str
    amount_cents: int
    reinvested_cents: int
    arose_at: str
    reinvest_by_at: str
    status: str
    satisfied_at: Optional[str]
    breached_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommunityBenefitsAgreement(TypedDict):
    id: str
    qalicb_id: str
    allocation_award_id: str
    target_fte_count: int
    wage_floor_cents_per_hour: int
    local_hire_pct_target: float
    measurement_basis: str
    agreement_start_at: str
    status: str
    consecutive_cure_required_count: int
    latest_compliance_pct: float
    latest_local_hire_pct: float
    last_certified_year: Optional[int]
    breached_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnwindTransaction(TypedDict):
    id: str
    qei_id: str
    put_holder_user_id: str
    call_holder_user_id: str
    fund_residual_value_cents: int
    put_price_cents: int
    call_price_cents: int
    option_window_open_at: str
    option_window_close_at: str
    status: str
    exercised_option_type: Optional[str]
    exercised_at: Optional[str]
    settlement_amount_cents: int
    settlement_reference: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only observations: id + created_at only ------------------------


class CensusTract(TypedDict):
    id: str
    tract_code: str
    state_code: str
    poverty_rate_pct: float
    mfi_ratio_pct: float
    unemployment_ratio: float
    contiguous_lic_tract_id: Optional[str]
    is_low_income_community: bool
    qualifies_by_contiguity: bool
    eligible_for_qlici: bool
    severe_criteria_met_count: int
    distress_score: float
    distress_tier: str
    created_at: str


class EligibilityTest(TypedDict):
    id: str
    qalicb_id: str
    gross_income_lic_pct: float
    services_lic_pct: float
    tangible_property_lic_pct: float
    collectibles_pct: float
    nonqualified_financial_property_pct: float
    location_prong_passed: bool
    result: str
    failed_prongs: List[str]
    performed_by_user_id: str
    performed_at: str
    created_at: str


class AnnualComplianceTest(TypedDict):
    id: str
    qei_id: str
    compliance_year: int
    window_start_at: str
    window_end_at: str
    window_days: int
    measured_pct_direct: float
    measured_pct_aggregate: float
    governing_method: str
    governing_pct: float
    result: str
    breached_obligation_count: int
    recertification_swept_qalicb_count: int
    recapture_triggered: bool
    performed_by_user_id: str
    created_at: str


class JobReport(TypedDict):
    id: str
    community_benefits_agreement_id: str
    period_start_at: str
    period_end_at: str
    headcount: int
    qualifying_headcount: int
    total_hours: int
    qualifying_hours: int
    local_hires: int
    avg_hourly_wage_cents: int
    wage_floor_met: bool
    filed_by_user_id: str
    filed_at: str
    created_at: str


# --- Computed snapshot responses (not stored resources) -------------------


class AgencyReport(TypedDict):
    allocation_award_id: str
    report_year: int
    issued_qei_count: int
    deployed_principal_cents: int
    qualifying_qalicb_count: int
    severe_distress_share_pct: float
    severe_distress_shortfall: bool
    at_risk_qei_count: int
    recaptured_qei_count: int
    cba_breach_count: int


class AnnualCertification(TypedDict):
    community_benefits_agreement_id: str
    certification_year: int
    measurement_basis: str
    achieved_fte: float
    compliance_pct: float
    local_hire_pct: float
    report_count: int
    excluded_wage_failing_report_count: int
    classification: str
    resulting_status: str


#: Resources that carry the full common-field set.
VERSIONED_RESOURCES = [
    "cde",
    "allocation_award",
    "qalicb",
    "investment_fund",
    "qei",
    "qlici",
    "reinvestment_obligation",
    "community_benefits_agreement",
    "unwind_transaction",
]

#: Append-only observations, which carry neither `updated_at` nor `version`.
APPEND_ONLY_RESOURCES = [
    "census_tract",
    "eligibility_test",
    "annual_compliance_test",
    "job_report",
]
