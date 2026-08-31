"""Domain types for the indirect auto lending dealer reserve API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PORTFOLIO_ADMIN = "PortfolioAdmin"
    CREDIT_ANALYST = "CreditAnalyst"
    FUNDING_SPECIALIST = "FundingSpecialist"
    DEALER_PRINCIPAL = "DealerPrincipal"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class DealerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class DealerStatusAction(str, Enum):
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    TERMINATE = "TERMINATE"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"
    RELEASE_HOLD = "RELEASE_HOLD"


class AgreementStatus(str, Enum):
    PENDING_COUNTERSIGN = "PENDING_COUNTERSIGN"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class ParticipationMethod(str, Enum):
    RATE_PARTICIPATION = "RATE_PARTICIPATION"
    FLAT_FEE = "FLAT_FEE"


class RateSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class TierCode(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONDITIONED = "CONDITIONED"
    RESUBMITTED = "RESUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ON_HOLD = "ON_HOLD"
    WITHDRAWN = "WITHDRAWN"
    CONTRACTED = "CONTRACTED"


class DecisionOutcome(str, Enum):
    APPROVE = "APPROVE"
    CONDITION = "CONDITION"
    DECLINE = "DECLINE"


class MonitoringCohort(str, Enum):
    CONTROL = "CONTROL"
    MONITORED = "MONITORED"


class FundingStatus(str, Enum):
    PENDING_DOCS = "PENDING_DOCS"
    DOCS_VERIFIED = "DOCS_VERIFIED"
    FUNDED = "FUNDED"
    PAID_OFF = "PAID_OFF"
    DEFAULTED = "DEFAULTED"
    REPURCHASED = "REPURCHASED"


class ReserveStatus(str, Enum):
    NONE = "NONE"
    ACCRUED = "ACCRUED"
    HELD = "HELD"
    CHARGED_BACK = "CHARGED_BACK"
    EARNED = "EARNED"


class DocType(str, Enum):
    RETAIL_INSTALLMENT_CONTRACT = "RETAIL_INSTALLMENT_CONTRACT"
    TITLE_APPLICATION = "TITLE_APPLICATION"
    INSURANCE_BINDER = "INSURANCE_BINDER"
    INCOME_VERIFICATION = "INCOME_VERIFICATION"


class DocumentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class VerifyOutcome(str, Enum):
    VERIFY = "VERIFY"
    REJECT = "REJECT"


class EntryType(str, Enum):
    PARTICIPATION_ACCRUAL = "PARTICIPATION_ACCRUAL"
    INCENTIVE_ACCRUAL = "INCENTIVE_ACCRUAL"
    CHARGEBACK = "CHARGEBACK"
    BUYBACK_OFFSET = "BUYBACK_OFFSET"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    REMEDIATION = "REMEDIATION"


class EventType(str, Enum):
    EARLY_PAYOFF = "EARLY_PAYOFF"
    DEFAULT = "DEFAULT"


class ScorecardBasis(str, Enum):
    TRAILING_WINDOW = "TRAILING_WINDOW"
    INCEPTION_TO_DATE = "INCEPTION_TO_DATE"


class ScorecardStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNRATED = "UNRATED"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    REMEDIATION_ORDERED = "REMEDIATION_ORDERED"
    CLOSED = "CLOSED"


class ReviewFinding(str, Enum):
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    EXCEEDS_THRESHOLD = "EXCEEDS_THRESHOLD"


class BuybackStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class BuybackReason(str, Enum):
    DOC_DEFECT = "DOC_DEFECT"
    EARLY_DEFAULT = "EARLY_DEFAULT"
    FRAUD = "FRAUD"
    DEALER_TERMINATION = "DEALER_TERMINATION"


# --- Entity shapes ---------------------------------------------------------
# Resources carrying id + created_at + updated_at + version.

class Dealer(TypedDict):
    id: str
    legal_name: str
    state_code: str
    program_code: str
    funding_line_cents: int
    status: str
    compliance_hold: bool
    suspension_reason: Optional[str]
    reserve_balance_cents: int
    outstanding_principal_cents: int
    funded_contract_count: int
    total_funded_ever_count: int
    early_payoff_count: int
    default_count: int
    repurchase_count: int
    chargeback_count: int
    early_payoff_rate_bps: int
    latest_scorecard_grade: Optional[str]
    scorecard_stale: bool
    created_at: str
    updated_at: str
    version: int


class DealerAgreement(TypedDict):
    id: str
    dealer_id: str
    supersedes_agreement_id: Optional[str]
    participation_method: str
    max_participation_bps: int
    flat_fee_cap_cents: int
    chargeback_window_days: int
    effective_from: str
    effective_to: str
    status: str
    countersigned_at: Optional[str]
    signer_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateSheet(TypedDict):
    id: str
    program_code: str
    effective_from: str
    effective_to: str
    status: str
    tier_count: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditApplication(TypedDict):
    id: str
    dealer_id: str
    agreement_id: Optional[str]
    rate_sheet_id: Optional[str]
    assigned_tier_id: Optional[str]
    applicant_reference: str
    monitoring_cohort: str
    credit_score: int
    monthly_income_cents: int
    monthly_debt_cents: int
    amount_financed_cents: int
    collateral_value_cents: int
    term_months: int
    vehicle_model_year: int
    requested_apr_bps: int
    ltv_pct: float
    dti_pct: float
    base_tier_code: Optional[str]
    demotion_count: int
    assigned_tier_code: Optional[str]
    buy_rate_apr_bps: Optional[int]
    max_contract_apr_bps: Optional[int]
    status: str
    held_from_status: Optional[str]
    resubmission_count: int
    stipulation_count: int
    decisioned_by_user_id: Optional[str]
    decisioned_at: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailContract(TypedDict):
    id: str
    application_id: str
    dealer_id: str
    agreement_id: str
    contract_apr_bps: int
    contract_date: str
    amount_financed_cents: int
    term_months: int
    buy_rate_apr_bps: int
    markup_bps: int
    monitoring_cohort: str
    acquisition_fee_cents: int
    required_doc_types: List[str]
    funding_status: str
    reserve_status: str
    verified_doc_count: int
    doc_defect_count: int
    funded_at: Optional[str]
    funded_by_user_id: Optional[str]
    reserve_accrued_cents: int
    incentive_accrued_cents: int
    dealer_proceeds_cents: int
    unpaid_principal_cents: int
    payoff_months_seasoned: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ContractDocument(TypedDict):
    id: str
    contract_id: str
    doc_type: str
    document_reference: str
    status: str
    defect_code: Optional[str]
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DealerScorecard(TypedDict):
    id: str
    dealer_id: str
    period_start: str
    period_end: str
    basis: str
    population_count: int
    default_rate_bps: int
    early_payoff_rate_bps: int
    doc_defect_rate_bps: int
    avg_markup_bps: int
    composite_score: Optional[int]
    grade: str
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FairLendingReview(TypedDict):
    id: str
    dealer_id: str
    window_start: str
    window_end: str
    population_count: int
    benchmark_markup_bps: int
    control_avg_markup_bps: int
    monitored_avg_markup_bps: int
    disparity_bps: int
    finding: str
    remediation_pool_cents: int
    status: str
    published_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuybackDemand(TypedDict):
    id: str
    contract_id: str
    dealer_id: str
    reason: str
    status: str
    unpaid_principal_cents: int
    reserve_offset_cents: int
    admin_fee_cents: int
    buyback_amount_cents: int
    dispute_reason: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Resources that are historical facts: they carry ONLY id and created_at.

class RateSheetTier(TypedDict):
    id: str
    rate_sheet_id: str
    tier_code: str
    min_credit_score: int
    max_credit_score: int
    max_ltv_pct: int
    max_term_months: int
    buy_rate_apr_bps: int
    advance_rate_pct: int
    acquisition_fee_cents: int
    created_at: str


class ReserveEntry(TypedDict):
    id: str
    dealer_id: str
    contract_id: Optional[str]
    entry_type: str
    amount_cents: int
    reason: str
    balance_after_cents: int
    created_at: str


class ChargebackEvent(TypedDict):
    id: str
    contract_id: str
    event_type: str
    event_date: str
    months_seasoned: int
    window_months: int
    within_window: bool
    participation_chargeback_cents: int
    incentive_chargeback_cents: int
    chargeback_total_cents: int
    earned_to_date_reserve_cents: int
    created_at: str
