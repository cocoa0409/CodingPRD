"""Domain types for the Manufactured Home Chattel Lending API.

Entity shapes, status enumerations and the role enumeration, all named exactly
as the PRD names them.  Entities that the PRD declares immutable carry only
``id`` and ``created_at`` — they have no ``updated_at`` and no ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enumeration (PRD §2.1) ──────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CREDIT_ANALYST = "CreditAnalyst"
    CLOSING_AGENT = "ClosingAgent"
    SERVICER = "Servicer"
    RECOVERY_MANAGER = "RecoveryManager"
    COMMUNITY_OPERATOR = "CommunityOperator"
    BORROWER = "Borrower"


# ─── Status enumerations ──────────────────────────────

class BorrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OperatorAgreementStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class OperatorAgreementAction(str, Enum):
    PROPOSE = "PROPOSE"
    EXECUTE = "EXECUTE"
    TERMINATE = "TERMINATE"


class WidthClass(str, Enum):
    SINGLE_WIDE = "SINGLE_WIDE"
    MULTI_WIDE = "MULTI_WIDE"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class InstallationType(str, Enum):
    PIER_AND_ANCHOR = "PIER_AND_ANCHOR"
    PERMANENT_FOUNDATION = "PERMANENT_FOUNDATION"


class PlacementType(str, Enum):
    COMMUNITY = "COMMUNITY"
    PRIVATE_LAND = "PRIVATE_LAND"


class UnitClassification(str, Enum):
    PERSONAL_PROPERTY = "PERSONAL_PROPERTY"
    CONVERSION_PENDING = "CONVERSION_PENDING"
    REAL_PROPERTY = "REAL_PROPERTY"


class TitleStatus(str, Enum):
    ACTIVE_TITLE = "ACTIVE_TITLE"
    TITLE_ENCUMBERED = "TITLE_ENCUMBERED"
    TITLE_SURRENDERED = "TITLE_SURRENDERED"


class LandDocumentType(str, Enum):
    DEED = "DEED"
    AFFIXATION_AFFIDAVIT = "AFFIXATION_AFFIDAVIT"


class ConversionAction(str, Enum):
    INITIATE = "INITIATE"
    COMPLETE = "COMPLETE"
    RESCIND = "RESCIND"


class ValuationVariant(str, Enum):
    ORIGINATION = "ORIGINATION"
    RECOVERY_LIQUIDATION = "RECOVERY_LIQUIDATION"


class ValuationStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class LocationKey(str, Enum):
    COMMUNITY_WITH_AGREEMENT = "COMMUNITY_WITH_AGREEMENT"
    COMMUNITY_WITHOUT_AGREEMENT = "COMMUNITY_WITHOUT_AGREEMENT"
    PRIVATE_LAND = "PRIVATE_LAND"


class UnderwritingState(str, Enum):
    DRAFT = "DRAFT"
    UNDERWRITING = "UNDERWRITING"
    APPROVED = "APPROVED"
    FUNDED = "FUNDED"
    DECLINED = "DECLINED"


class ServicingState(str, Enum):
    NOT_SERVICING = "NOT_SERVICING"
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"
    RECOVERY = "RECOVERY"
    PAID_OFF = "PAID_OFF"
    CHARGED_OFF = "CHARGED_OFF"


class PerfectionState(str, Enum):
    UNPERFECTED = "UNPERFECTED"
    FILING_SUBMITTED = "FILING_SUBMITTED"
    PERFECTED = "PERFECTED"
    RE_PERFECTION_REQUIRED = "RE_PERFECTION_REQUIRED"
    RELEASED = "RELEASED"


class InsuranceCompliance(str, Enum):
    UNKNOWN = "UNKNOWN"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class FilingType(str, Enum):
    TITLE_LIEN = "TITLE_LIEN"
    LAND_HOME_DEED_OF_TRUST = "LAND_HOME_DEED_OF_TRUST"


class FilingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECORDED = "RECORDED"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"


class FilingDocument(str, Enum):
    TITLE_APPLICATION = "TITLE_APPLICATION"
    LIEN_ENTRY_FORM = "LIEN_ENTRY_FORM"
    DEED_OF_TRUST = "DEED_OF_TRUST"
    AFFIXATION_AFFIDAVIT = "AFFIXATION_AFFIDAVIT"
    TITLE_SURRENDER_RECEIPT = "TITLE_SURRENDER_RECEIPT"


class RejectionCode(str, Enum):
    MISSING_DOCUMENT = "MISSING_DOCUMENT"
    NAME_MISMATCH = "NAME_MISMATCH"
    FEE_SHORTFALL = "FEE_SHORTFALL"


class AgencyOutcome(str, Enum):
    RECORDED = "RECORDED"
    REJECTED = "REJECTED"


class PolicySource(str, Enum):
    BORROWER_PROVIDED = "BORROWER_PROVIDED"
    FORCE_PLACED = "FORCE_PLACED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class ComplianceState(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT_WIND = "DEFICIENT_WIND"
    DEFICIENT_COVERAGE = "DEFICIENT_COVERAGE"


class PaymentKind(str, Enum):
    SCHEDULED = "SCHEDULED"
    PARTIAL = "PARTIAL"
    PAYOFF = "PAYOFF"
    REVERSAL = "REVERSAL"


class AllocationVariant(str, Enum):
    CHATTEL_CONTRACT_ORDER = "CHATTEL_CONTRACT_ORDER"
    REAL_PROPERTY_ESCROW_FIRST = "REAL_PROPERTY_ESCROW_FIRST"


class LotRentState(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    EVICTION_FILED = "EVICTION_FILED"


class RecoveryPath(str, Enum):
    REPOSSESSION = "REPOSSESSION"
    FORECLOSURE = "FORECLOSURE"


class RecoveryCaseStatus(str, Enum):
    OPENED = "OPENED"
    REPO_NOTICE_ISSUED = "REPO_NOTICE_ISSUED"
    REDEMPTION_WINDOW = "REDEMPTION_WINDOW"
    POSSESSION_OBTAINED = "POSSESSION_OBTAINED"
    REFURBISHING = "REFURBISHING"
    REMARKETING = "REMARKETING"
    CLOSED_REDEEMED = "CLOSED_REDEEMED"
    CLOSED_DEFICIENCY = "CLOSED_DEFICIENCY"
    CLOSED_SURPLUS = "CLOSED_SURPLUS"
    CLOSED_SETTLED = "CLOSED_SETTLED"


class CostClass(str, Enum):
    CAPITALIZED = "CAPITALIZED"
    EXPENSED = "EXPENSED"


# ─── Entity shapes ────────────────────────────────────
# A BookValueGuide and a PaymentTransaction are immutable, so they carry only
# ``id`` and ``created_at`` (PRD §2.5).  Every other entity carries the full
# set of four audit properties.

class BookValueGuide(TypedDict):
    id: str
    guide_edition: str
    region_code: str
    effective_date: str
    base_value_per_sqft_cents: int
    single_wide_multiplier_bps: int
    multi_wide_multiplier_bps: int
    annual_depreciation_bps: int
    created_at: str


class Borrower(TypedDict):
    id: str
    full_name: str
    credit_score: int
    monthly_income_cents: int
    state_code: str
    status: str
    total_outstanding_principal_cents: int
    units_under_recovery_hold_count: int
    created_at: str
    updated_at: str
    version: int


class Community(TypedDict):
    id: str
    name: str
    state_code: str
    lot_count: int
    monthly_lot_rent_cents: int
    sales_commission_bps: int
    operator_agreement_status: str
    lender_access_rights: bool
    agreement_executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ManufacturedUnit(TypedDict):
    id: str
    hud_label_number: str
    manufacturer: str
    model_year: int
    width_class: str
    square_feet: int
    condition_grade: str
    installation_type: str
    wind_zone: int
    placement_type: str
    community_id: Optional[str]
    lot_number: Optional[str]
    placement_start_date: Optional[str]
    placement_end_date: Optional[str]
    land_owner_borrower_id: Optional[str]
    land_parcel_apn: Optional[str]
    land_county: Optional[str]
    land_value_cents: int
    classification: str
    title_status: str
    recovery_hold: bool
    deed_recorded: bool
    affixation_affidavit_recorded: bool
    created_at: str
    updated_at: str
    version: int


class Valuation(TypedDict):
    id: str
    unit_id: str
    guide_id: str
    variant: str
    status: str
    valuation_year: int
    location_key: str
    book_base_cents: int
    condition_adjustment_cents: int
    location_adjustment_cents: int
    installation_adjustment_cents: int
    forced_sale_discount_cents: int
    detach_and_move_cost_cents: int
    certified_value_cents: int
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    borrower_id: str
    unit_id: str
    origination_valuation_id: str
    refinanced_from_loan_id: Optional[str]
    principal_cents: int
    requested_term_months: int
    collateral_classification: str
    placement_type: str
    ltv_bps: Optional[int]
    apr_bps: Optional[int]
    term_months: Optional[int]
    underwriting_state: str
    servicing_state: str
    perfection_state: str
    insurance_compliance: str
    approved_by_user_id: Optional[str]
    decline_reason: Optional[str]
    funded_at: Optional[str]
    next_due_date: Optional[str]
    last_accrual_date: Optional[str]
    delinquent_days: int
    principal_balance_cents: int
    interest_accrued_unpaid_cents: int
    fees_outstanding_cents: int
    force_placed_premium_outstanding_cents: int
    escrow_balance_cents: int
    escrow_target_cents: int
    lot_rent_months_delinquent: int
    lot_rent_state: str
    created_at: str
    updated_at: str
    version: int


class LienFiling(TypedDict):
    id: str
    loan_id: str
    unit_id: str
    filing_type: str
    submitted_documents: List[str]
    missing_documents: List[str]
    status: str
    attempt_number: int
    agency_reference: Optional[str]
    rejection_code: Optional[str]
    recorded_at: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    loan_id: str
    carrier_name: str
    policy_number: str
    source: str
    status: str
    dwelling_coverage_cents: int
    wind_deductible_cents: int
    wind_endorsement: bool
    effective_date: str
    expiry_date: str
    coverage_days: int
    required_coverage_cents: int
    compliance_state: str
    premium_cents: int
    unearned_premium_refund_cents: int
    created_at: str
    updated_at: str
    version: int


class PaymentTransaction(TypedDict):
    id: str
    loan_id: str
    payment_kind: str
    amount_cents: int
    posted_at: str
    accrual_days: int
    accrued_interest_at_posting_cents: int
    allocation_variant: str
    to_interest_cents: int
    to_fees_cents: int
    to_force_placed_cents: int
    to_escrow_cents: int
    to_principal_cents: int
    reversed: bool
    reverses_payment_id: Optional[str]
    reversal_reason: Optional[str]
    created_at: str


class RefurbishmentLineItem(TypedDict):
    category: str
    cost_cents: int
    cost_class: str
    recorded_at: str


class RecoveryCase(TypedDict):
    id: str
    loan_id: str
    status: str
    path: str
    recovery_expense_cents: int
    cure_deadline_date: Optional[str]
    redemption_window_ends_at: Optional[str]
    possession_date: Optional[str]
    recovery_valuation_id: Optional[str]
    refurbishment_line_items: List[RefurbishmentLineItem]
    refurbishment_cost_cents: int
    asking_price_cents: Optional[int]
    resale_price_cents: Optional[int]
    resale_loan_id: Optional[str]
    gross_proceeds_cents: Optional[int]
    commission_bps: Optional[int]
    commission_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    payoff_amount_cents: Optional[int]
    deficiency_balance_cents: Optional[int]
    surplus_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
