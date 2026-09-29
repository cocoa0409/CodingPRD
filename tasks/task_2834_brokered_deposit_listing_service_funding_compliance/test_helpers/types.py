"""Domain types for the Brokered Deposit & Listing Service Funding Compliance API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Records the PRD declares append-only carry only ``id`` and
``created_at`` -- no ``updated_at`` and no ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum (PRD §2.1) ─────────────────────────────

class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    FUNDING_DESK_OFFICER = "FundingDeskOfficer"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    TREASURY_CONTROLLER = "TreasuryController"
    EXAMINER = "Examiner"
    BROKER_REPRESENTATIVE = "BrokerRepresentative"


# ─── Enumerations ─────────────────────────────────────

class CapitalCategory(str, Enum):
    WELL_CAPITALIZED = "WELL_CAPITALIZED"
    ADEQUATELY_CAPITALIZED = "ADEQUATELY_CAPITALIZED"
    UNDERCAPITALIZED = "UNDERCAPITALIZED"
    SIGNIFICANTLY_UNDERCAPITALIZED = "SIGNIFICANTLY_UNDERCAPITALIZED"
    CRITICALLY_UNDERCAPITALIZED = "CRITICALLY_UNDERCAPITALIZED"


class RateCapRegime(str, Enum):
    EXEMPT = "EXEMPT"
    CAPPED = "CAPPED"


class ConcentrationPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class TenorBucket(str, Enum):
    NON_MATURITY = "NON_MATURITY"
    DAYS_1_30 = "DAYS_1_30"
    DAYS_31_90 = "DAYS_31_90"
    DAYS_91_180 = "DAYS_91_180"
    DAYS_181_365 = "DAYS_181_365"
    DAYS_366_PLUS = "DAYS_366_PLUS"


class BrokerType(str, Enum):
    DEPOSIT_BROKER = "DEPOSIT_BROKER"
    LISTING_SERVICE = "LISTING_SERVICE"
    DEPOSIT_PLACEMENT_NETWORK = "DEPOSIT_PLACEMENT_NETWORK"
    AFFILIATE = "AFFILIATE"


class FeeStructure(str, Enum):
    FLAT_FEE = "FLAT_FEE"
    BASIS_POINT_FEE = "BASIS_POINT_FEE"
    VOLUME_TIERED = "VOLUME_TIERED"
    PER_ACCOUNT_FEE = "PER_ACCOUNT_FEE"


class DiligenceStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_DILIGENCE = "IN_DILIGENCE"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_DILIGENCE = "UNDER_DILIGENCE"
    RFI_ISSUED = "RFI_ISSUED"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ExceptionBasis(str, Enum):
    TWENTY_FIVE_PERCENT_TEST = "TWENTY_FIVE_PERCENT_TEST"
    ENABLING_TRANSACTIONS_TEST = "ENABLING_TRANSACTIONS_TEST"
    OTHER_APPLICATION = "OTHER_APPLICATION"


class FilingType(str, Enum):
    NOTICE = "NOTICE"
    APPLICATION = "APPLICATION"


class TestOutcome(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"


class ExceptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    REVOKED = "REVOKED"


class FundingChannelClaim(str, Enum):
    BROKERED = "BROKERED"
    LISTING_SERVICE = "LISTING_SERVICE"
    CORE = "CORE"
    RECIPROCAL_NETWORK = "RECIPROCAL_NETWORK"


class ProductType(str, Enum):
    TIME_DEPOSIT = "TIME_DEPOSIT"
    MONEY_MARKET = "MONEY_MARKET"
    SAVINGS = "SAVINGS"
    NOW = "NOW"


class TitlingConvention(str, Enum):
    SINGLE_FIDUCIARY_ACCOUNT = "SINGLE_FIDUCIARY_ACCOUNT"
    FBO_SUBACCOUNTS = "FBO_SUBACCOUNTS"
    DIRECT_TITLED = "DIRECT_TITLED"


class ProgramState(str, Enum):
    PENDING_CLASSIFICATION = "PENDING_CLASSIFICATION"
    CLASSIFIED = "CLASSIFIED"
    OPEN_FOR_PLACEMENT = "OPEN_FOR_PLACEMENT"
    SUSPENDED = "SUSPENDED"
    RECLASSIFICATION_PENDING = "RECLASSIFICATION_PENDING"
    CLOSED = "CLOSED"


class DeterminedClass(str, Enum):
    BROKERED = "BROKERED"
    LISTING_SERVICE_NON_BROKERED = "LISTING_SERVICE_NON_BROKERED"
    CORE = "CORE"
    RECIPROCAL_EXCLUDED = "RECIPROCAL_EXCLUDED"


class DepositBrokerProng(str, Enum):
    PLACEMENT_DISCRETION = "PLACEMENT_DISCRETION"
    MATCHING_DRIVER = "MATCHING_DRIVER"
    FEE_FOR_PLACEMENT = "FEE_FOR_PLACEMENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CallReportLine(str, Enum):
    RC_E_M1_BROKERED = "RC_E_M1_BROKERED"
    RC_E_M2_LISTING = "RC_E_M2_LISTING"
    RC_E_CORE = "RC_E_CORE"
    RC_O_M_RECIPROCAL = "RC_O_M_RECIPROCAL"


class FundingStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    MATURED = "MATURED"
    WITHDRAWN_EARLY = "WITHDRAWN_EARLY"
    ROLLED_OVER = "ROLLED_OVER"
    CANCELLED = "CANCELLED"


class ComplianceStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    RATE_CHECKED = "RATE_CHECKED"
    FLAGGED = "FLAGGED"
    REMEDIATED = "REMEDIATED"


class RateCapOutcome(str, Enum):
    PASS = "PASS"
    BREACH = "BREACH"
    EXEMPT_NO_CAP = "EXEMPT_NO_CAP"


class ConcentrationMetric(str, Enum):
    BROKERED_TO_TOTAL_DEPOSITS = "BROKERED_TO_TOTAL_DEPOSITS"
    LISTING_TO_TOTAL_DEPOSITS = "LISTING_TO_TOTAL_DEPOSITS"
    WHOLESALE_TO_TOTAL_LIABILITIES = "WHOLESALE_TO_TOTAL_LIABILITIES"
    SINGLE_BROKER_TO_TOTAL_DEPOSITS = "SINGLE_BROKER_TO_TOTAL_DEPOSITS"


class LimitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BreachState(str, Enum):
    WITHIN = "WITHIN"
    WARNING = "WARNING"
    BREACH = "BREACH"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ACTIVATED = "ACTIVATED"
    DEACTIVATED = "DEACTIVATED"


class ActivationStage(str, Enum):
    NONE = "NONE"
    STAGE_1_MONITOR = "STAGE_1_MONITOR"
    STAGE_2_CONTINGENT = "STAGE_2_CONTINGENT"
    STAGE_3_CRISIS = "STAGE_3_CRISIS"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    PREPARED = "PREPARED"
    ATTESTED = "ATTESTED"
    FILED = "FILED"
    UNDER_EXAMINER_REVIEW = "UNDER_EXAMINER_REVIEW"
    AMENDMENT_REQUIRED = "AMENDMENT_REQUIRED"
    ACCEPTED = "ACCEPTED"


class AccuracyStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    ACCURATE = "ACCURATE"
    VARIANCE_MINOR = "VARIANCE_MINOR"
    VARIANCE_MATERIAL = "VARIANCE_MATERIAL"


class WholesaleBasis(str, Enum):
    POINT_IN_TIME = "POINT_IN_TIME"
    AVERAGE_DAILY = "AVERAGE_DAILY"


# ─── Entity TypedDicts ────────────────────────────────
# Institution, Broker, BrokerAgreement, PrimaryPurposeException,
# DepositProgram, DepositPlacement, ConcentrationLimit,
# LiquidityContingencyPlan and CallReportFiling carry
# id + created_at + updated_at + version (PRD §2.5).

class Institution(TypedDict):
    id: str
    legal_name: str
    cert_id: str
    capital_category: str
    rate_cap_regime: str
    core_deposits_cents: int
    brokered_deposits_cents: int
    listing_service_deposits_cents: int
    reciprocal_deposits_cents: int
    total_deposits_cents: int
    total_liabilities_cents: int
    tier1_capital_cents: int
    liquidity_buffer_cents: int
    wholesale_funding_ratio_bps: int
    single_broker_max_ratio_bps: int
    concentration_posture: str
    breached_metric_count: int
    created_at: str
    updated_at: str
    version: int


class Broker(TypedDict):
    id: str
    legal_name: str
    broker_type: str
    has_placement_discretion: bool
    fee_structure: str
    fee_bps: int
    fee_flat_cents: int
    diligence_status: str
    approved_agreement_count: int
    created_at: str
    updated_at: str
    version: int


class BrokerAgreement(TypedDict):
    id: str
    broker_id: str
    agreement_ref: str
    status: str
    fee_structure: str
    fee_bps: int
    fee_flat_cents: int
    termination_notice_days: int
    effective_date: str
    aml_program_score: int
    financial_condition_score: int
    insurance_coverage_score: int
    recordkeeping_score: int
    diligence_score: int
    rfi_round_count: int
    accrued_fee_cents: int
    prepared_by_user_id: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrimaryPurposeException(TypedDict):
    id: str
    broker_id: str
    institution_id: str
    exception_basis: str
    filing_type: str
    designated_business_line: str
    total_customer_assets_cents: int
    deposits_placed_at_ifs_cents: int
    enabling_transaction_count: int
    total_transaction_count: int
    business_line_deposit_ratio_bps: int
    enabling_transaction_ratio_bps: int
    test_outcome: str
    status: str
    info_request_round_count: int
    reporting_due_date: Optional[str]
    reliant_program_count: int
    prepared_by_user_id: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DepositProgram(TypedDict):
    id: str
    institution_id: str
    broker_id: Optional[str]
    agreement_id: Optional[str]
    governing_classification_id: Optional[str]
    program_name: str
    funding_channel_claim: str
    product_type: str
    tenor_days: int
    tenor_bucket: str
    offered_rate_bps: int
    local_prevailing_rate_bps: Optional[int]
    effective_cap_bps: Optional[int]
    early_withdrawal_penalty_days: int
    principal_erosion_allowed: bool
    pass_through_insurance: bool
    titling_convention: str
    rollover_enabled: bool
    reciprocal_arrangement_cents: int
    state: str
    outstanding_principal_cents: int
    prepared_by_user_id: str
    attested_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DepositPlacement(TypedDict):
    id: str
    program_id: str
    rolled_from_placement_id: Optional[str]
    principal_cents: int
    rate_bps: int
    issue_date: str
    tenor_days: int
    maturity_date: str
    tenor_bucket: str
    funding_status: str
    compliance_status: str
    accrued_interest_cents: int
    early_withdrawal_penalty_cents: int
    net_settlement_cents: int
    settlement_date: Optional[str]
    fee_accrual_cents: int
    classified_as: Optional[str]
    prepared_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ConcentrationLimit(TypedDict):
    id: str
    institution_id: str
    metric: str
    warning_threshold_bps: int
    breach_threshold_bps: int
    status: str
    current_value_bps: int
    breach_state: str
    created_at: str
    updated_at: str
    version: int


class LiquidityContingencyPlan(TypedDict):
    id: str
    institution_id: str
    plan_version_label: str
    effective_from: str
    effective_to: str
    status: str
    activation_stage: str
    stage_1_trigger_bps: int
    stage_2_trigger_bps: int
    stage_3_trigger_bps: int
    stage_1_action_code: str
    stage_2_action_code: str
    stage_3_action_code: str
    required_buffer_cents: int
    buffer_shortfall_cents: int
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CallReportFiling(TypedDict):
    id: str
    institution_id: str
    report_period: str
    rc_e_brokered_reported_cents: int
    rc_o_listing_reported_cents: int
    rc_e_core_reported_cents: int
    computed_brokered_cents: int
    computed_listing_cents: int
    computed_core_cents: int
    variance_cents: int
    variance_bps: int
    accuracy_status: str
    status: str
    amendment_round: int
    examiner_finding_note: Optional[str]
    prepared_by_user_id: Optional[str]
    attested_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only ledger records (PRD §2.5) ────────────
# A published national rate benchmark, a classification determination and a
# rate-cap check are written once and never edited: only id and created_at.

class NationalRateCap(TypedDict):
    id: str
    tenor_bucket: str
    published_national_rate_bps: int
    effective_date: str
    cap_bps: int
    non_maturity_cap_bps: int
    published_by_user_id: str
    created_at: str


class DepositClassification(TypedDict):
    id: str
    program_id: str
    relied_exception_id: Optional[str]
    determined_class: str
    deposit_broker_prong: str
    call_report_line: str
    rationale_code: str
    determined_by_user_id: str
    effective_at: str
    program_version_at_determination: int
    created_at: str


class RateCapCheck(TypedDict):
    id: str
    placement_id: str
    check_date: str
    applied_tenor_bucket: str
    national_rate_bps_snapshot: int
    local_prevailing_rate_bps_snapshot: Optional[int]
    effective_cap_bps: Optional[int]
    offered_rate_bps: int
    breach_bps: int
    outcome: str
    checked_by_user_id: str
    created_at: str
