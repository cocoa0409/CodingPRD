"""Domain types: entity TypedDicts, status enums and the role enum (PRD §2, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BROKER = "Broker"
    SELLER = "Seller"
    BUYER = "Buyer"
    ESCROW_AGENT = "EscrowAgent"


class PermitType(str, Enum):
    PESTICIDE_APPLICATOR = "PESTICIDE_APPLICATOR"
    CONTRACTOR = "CONTRACTOR"
    BUSINESS_TAX = "BUSINESS_TAX"


class SellerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BuyerLicenseStatus(str, Enum):
    LICENSED = "LICENSED"
    PENDING = "PENDING"
    NONE = "NONE"


class BuyerQualificationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class VerificationPosture(str, Enum):
    EMPTY = "EMPTY"
    INCOMPLETE = "INCOMPLETE"
    COMPLETE = "COMPLETE"


class AccountVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    EXCLUDED = "EXCLUDED"


class AccountTransferStatus(str, Enum):
    PENDING = "PENDING"
    INTRODUCED = "INTRODUCED"
    TRANSFERRED = "TRANSFERRED"
    LOST = "LOST"
    REPLACED = "REPLACED"


class RouteDay(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"


class ChemicalBillingMethod(str, Enum):
    INCLUDED = "INCLUDED"
    PASS_THROUGH = "PASS_THROUGH"


class BillingFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class BillingSource(str, Enum):
    SELLER_UPLOAD = "SELLER_UPLOAD"
    BANK_VERIFIED = "BANK_VERIFIED"


class ValuationBasis(str, Enum):
    LISTED_BASIS = "LISTED_BASIS"
    VERIFIED_BASIS = "VERIFIED_BASIS"


class DealStatus(str, Enum):
    OFFER_SUBMITTED = "OFFER_SUBMITTED"
    COUNTERED = "COUNTERED"
    REPRICE_REQUIRED = "REPRICE_REQUIRED"
    ACCEPTED = "ACCEPTED"
    DILIGENCE_CLEARED = "DILIGENCE_CLEARED"
    FINANCING_APPROVED = "FINANCING_APPROVED"
    ESCROW_FUNDED = "ESCROW_FUNDED"
    CLOSED = "CLOSED"
    GUARANTEE_CLOSED = "GUARANTEE_CLOSED"
    TERMINATED = "TERMINATED"


class FinancingType(str, Enum):
    CASH = "CASH"
    SELLER_NOTE = "SELLER_NOTE"
    BANK_LOAN = "BANK_LOAN"
    SBA = "SBA"


class ClawbackStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MONITORING = "MONITORING"
    CLAWBACK_TRIGGERED = "CLAWBACK_TRIGGERED"
    SETTLED = "SETTLED"


class EscrowStatus(str, Enum):
    OPEN = "OPEN"
    FUNDED = "FUNDED"
    PARTIALLY_RELEASED = "PARTIALLY_RELEASED"
    RELEASED = "RELEASED"
    REFUNDED = "REFUNDED"


class LicenseTransferStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class RemedyBasis(str, Enum):
    REPLACEMENT_BASIS = "REPLACEMENT_BASIS"
    PRICE_ADJUSTMENT_BASIS = "PRICE_ADJUSTMENT_BASIS"


class AttritionEventType(str, Enum):
    CANCELLED = "CANCELLED"
    DOWNGRADED = "DOWNGRADED"
    RECOVERED = "RECOVERED"


class AttributedTo(str, Enum):
    NATURAL = "NATURAL"
    SELLER_SOLICITATION = "SELLER_SOLICITATION"
    BUYER_SERVICE_FAILURE = "BUYER_SERVICE_FAILURE"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (PRD §2.4)
# ---------------------------------------------------------------------------

class StateLicenseProfile(TypedDict):
    id: str
    state_code: str
    required_permit_types: List[str]
    reciprocity_states: List[str]
    transfer_processing_days: int
    cooling_off_days: int
    provisional_operation_allowed: bool
    created_at: str
    updated_at: str
    version: int


class Seller(TypedDict):
    id: str
    legal_name: str
    state_code: str
    license_number: str
    status: str
    suspension_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    legal_name: str
    state_code: str
    license_status: str
    prequalified_amount_cents: int
    qualification_status: str
    qualified_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteListing(TypedDict):
    id: str
    seller_id: str
    region_code: str
    state_code: str
    status: str
    asking_price_cents: int
    listed_mrr_cents: int
    listed_account_count: int
    exclusive_start_date: str
    exclusive_end_date: str
    claimed_recurring_mrr_cents: int
    claimed_repair_mrr_cents: int
    claimed_account_count: int
    verified_recurring_mrr_cents: int
    verified_repair_mrr_cents: int
    verified_account_count: int
    introductions_completed_count: int
    verification_posture: str
    withdrawal_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceAccount(TypedDict):
    id: str
    listing_id: str
    deal_id: Optional[str]
    replaced_account_id: Optional[str]
    customer_ref: str
    service_start_date: str
    route_day: str
    monthly_service_fee_cents: int
    avg_monthly_chemical_cents: int
    avg_monthly_repair_cents: int
    chemical_billing_method: str
    billing_frequency: str
    claimed_recurring_mrr_cents: int
    account_age_months: int
    verification_status: str
    transfer_status: str
    verified_recurring_mrr_cents: Optional[int]
    verified_repair_mrr_cents: Optional[int]
    verification_variance: Optional[float]
    verified_by_user_id: Optional[str]
    introduction_sequence_no: Optional[int]
    introduced_on: Optional[str]
    current_mrr_cents: Optional[int]
    exclusion_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteValuation(TypedDict):
    id: str
    listing_id: str
    basis: str
    recurring_mrr_cents: int
    repair_mrr_cents: int
    account_count: int
    weighted_avg_account_age_months: int
    base_multiple: float
    age_adjustment: float
    effective_multiple: float
    recurring_component_cents: int
    repair_component_cents: int
    valuation_cents: int
    computed_from_clock_utc: str
    is_superseded: bool
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    status: str
    offer_round: int
    offer_price_cents: int
    current_offer_price_cents: int
    financing_type: str
    down_payment_cents: int
    note_principal_cents: int
    retention_guarantee_days: int
    lender_name: Optional[str]
    approved_amount_cents: Optional[int]
    accepted_on: Optional[str]
    closed_at_utc: Optional[str]
    guarantee_start_utc: Optional[str]
    guarantee_end_utc: Optional[str]
    replacement_deadline_utc: Optional[str]
    holdback_release_utc: Optional[str]
    effective_multiple_at_close: Optional[float]
    commission_cents: Optional[int]
    holdback_cents: Optional[int]
    escrow_target_amount_cents: Optional[int]
    clawback_cap_cents: Optional[int]
    guaranteed_mrr_cents: Optional[int]
    retained_mrr_cents: Optional[int]
    attrited_mrr_cents: int
    replacement_mrr_cents: int
    net_attrition_mrr_cents: int
    allowance_mrr_cents: Optional[int]
    attrition_pct: float
    clawback_status: str
    non_solicitation_executed_on: Optional[str]
    non_solicitation_end_date: Optional[str]
    repricing_reason_code: Optional[str]
    termination_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscrowAccount(TypedDict):
    id: str
    deal_id: str
    status: str
    target_amount_cents: int
    holdback_amount_cents: int
    funded_amount_cents: int
    undisbursed_balance_cents: int
    holdback_balance_cents: int
    disbursed_to_broker_cents: int
    disbursed_to_seller_cents: int
    disbursed_to_buyer_cents: int
    funded_by_user_id: Optional[str]
    scheduled_holdback_release_utc: Optional[str]
    deposits_blocked: bool
    holdback_release_blocked: bool
    created_at: str
    updated_at: str
    version: int


class LicenseTransfer(TypedDict):
    id: str
    deal_id: str
    state_profile_id: str
    permit_type: str
    status: str
    applied_on: Optional[str]
    processing_window_end: Optional[str]
    decided_on: Optional[str]
    denial_reason_code: Optional[str]
    attempt_count: int
    waiver_basis: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClawbackSettlement(TypedDict):
    id: str
    deal_id: str
    escrow_id: Optional[str]
    remedy_basis: str
    status: str
    guaranteed_mrr_cents: int
    lost_natural_mrr_cents: int
    lost_solicited_mrr_cents: int
    lost_buyer_fault_mrr_cents: int
    recovered_mrr_cents: int
    replacement_credit_cap_cents: int
    replacement_credit_mrr_cents: int
    allowance_mrr_cents: int
    compensable_natural_mrr_cents: int
    compensable_solicited_mrr_cents: int
    raw_adjustment_cents: int
    adjustment_cents: int
    from_holdback_cents: int
    from_note_principal_cents: int
    seller_direct_due_cents: int
    holdback_release_to_seller_cents: int
    dispute_reason_code: Optional[str]
    computed_from_clock_utc: str
    settled_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only ledgers: id + created_at ONLY (PRD §2.4)
# ---------------------------------------------------------------------------

class BillingHistoryRecord(TypedDict):
    id: str
    account_id: str
    period_month: str
    billed_service_cents: int
    billed_chemical_cents: int
    billed_repair_cents: int
    collected_cents: int
    source: str
    collection_rate: float
    recurring_collected_cents: int
    repair_collected_cents: int
    created_at: str


class AttritionEvent(TypedDict):
    id: str
    deal_id: str
    account_id: str
    event_type: str
    effective_date: str
    mrr_delta_cents: int
    attributed_to: str
    recorded_by_role: str
    created_at: str
