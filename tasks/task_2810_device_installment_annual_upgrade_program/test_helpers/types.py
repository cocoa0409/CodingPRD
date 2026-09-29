"""Domain types for the Device Installment Upgrade Program API.

Entity shapes, status enums and the role enum, all named exactly as the PRD
names them. Three resources are append-only records of something that already
happened and therefore carry only ``id`` and ``created_at``: ``PaymentPosting``,
``DiagnosticReport`` and ``DelinquencyEvent``. Their TypedDicts below omit
``updated_at`` and ``version`` deliberately.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    RETAIL_ASSOCIATE = "RetailAssociate"
    CREDIT_UNDERWRITER = "CreditUnderwriter"
    SERVICE_TECHNICIAN = "ServiceTechnician"
    COLLECTIONS_OFFICER = "CollectionsOfficer"
    PROGRAM_ADMIN = "ProgramAdmin"


ALL_ROLES: List[str] = [r.value for r in UserRole]


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FINANCING_LOCKED = "FINANCING_LOCKED"
    CLOSED = "CLOSED"


class FinancingLockReason(str, Enum):
    DEFAULTED_LOAN = "DEFAULTED_LOAN"
    DEVICE_RETURN_DIAGNOSTIC_FAILURE = "DEVICE_RETURN_DIAGNOSTIC_FAILURE"


class CreditScoreBand(str, Enum):
    PRIME = "PRIME"
    NEAR_PRIME = "NEAR_PRIME"
    SUBPRIME = "SUBPRIME"


class CarrierCode(str, Enum):
    VERIZON = "VERIZON"
    ATT = "ATT"
    TMOBILE = "TMOBILE"
    ESIM_MVNO = "ESIM_MVNO"


class CarrierActivationState(str, Enum):
    PENDING = "PENDING"
    ACTIVATED = "ACTIVATED"
    PORT_ELIGIBLE = "PORT_ELIGIBLE"


class CreditApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CONDITIONAL_APPROVED = "CONDITIONAL_APPROVED"
    DECLINED = "DECLINED"
    VOIDED_BY_LOCK = "VOIDED_BY_LOCK"
    ORIGINATED = "ORIGINATED"


class DecisionReason(str, Enum):
    WITHIN_LIMIT = "WITHIN_LIMIT"
    CONDITIONAL_DOWN_PAYMENT_REQUIRED = "CONDITIONAL_DOWN_PAYMENT_REQUIRED"
    EXPOSURE_ABOVE_CONDITIONAL_BAND = "EXPOSURE_ABOVE_CONDITIONAL_BAND"
    CUSTOMER_FINANCING_LOCKED = "CUSTOMER_FINANCING_LOCKED"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    ROLLED_OVER = "ROLLED_OVER"


class LoanClosureReason(str, Enum):
    PROGRAM_CANCELLATION = "PROGRAM_CANCELLATION"
    UPGRADE_ROLLOVER = "UPGRADE_ROLLOVER"


class DelinquencyState(str, Enum):
    CURRENT = "CURRENT"
    GRACE = "GRACE"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"


class ProtectionCoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAST_DUE = "PAST_DUE"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOIDED = "VOIDED"


class PostingType(str, Enum):
    PAYMENT = "PAYMENT"
    REVERSAL = "REVERSAL"
    PAYOFF = "PAYOFF"


class ActivationStatus(str, Enum):
    UNACTIVATED = "UNACTIVATED"
    ACTIVATED = "ACTIVATED"
    DEACTIVATED = "DEACTIVATED"


class UnlockStatus(str, Enum):
    LOCKED = "LOCKED"
    UNLOCK_REQUESTED = "UNLOCK_REQUESTED"
    UNLOCKED = "UNLOCKED"


class PossessionStatus(str, Enum):
    WITH_CUSTOMER = "WITH_CUSTOMER"
    RETURN_PENDING = "RETURN_PENDING"
    RETURNED = "RETURNED"
    RETURN_FAILED = "RETURN_FAILED"


class UpgradeRequestStatus(str, Enum):
    ELIGIBILITY_PASSED = "ELIGIBILITY_PASSED"
    TRADE_IN_DECLARED = "TRADE_IN_DECLARED"
    TRADE_IN_GRADED = "TRADE_IN_GRADED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ExpiryReason(str, Enum):
    FULFILLMENT_WINDOW_ELAPSED = "FULFILLMENT_WINDOW_ELAPSED"
    CUSTOMER_FINANCING_LOCKED = "CUSTOMER_FINANCING_LOCKED"
    SUPERSEDED_BY_NEW_REQUEST = "SUPERSEDED_BY_NEW_REQUEST"


class FundingFlag(str, Enum):
    FUNDED = "FUNDED"
    REQUIRES_DOWN_PAYMENT = "REQUIRES_DOWN_PAYMENT"


class TradeInStatus(str, Enum):
    DECLARED = "DECLARED"
    RECEIVED = "RECEIVED"
    GRADED = "GRADED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class DeviceCondition(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class ScreenGrade(str, Enum):
    PRISTINE = "PRISTINE"
    SCRATCHED = "SCRATCHED"
    CRACKED = "CRACKED"


class DiagnosticResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ReportType(str, Enum):
    INITIAL = "INITIAL"
    REGRADE = "REGRADE"


class QuoteType(str, Enum):
    EARLY_CANCELLATION = "EARLY_CANCELLATION"
    UPGRADE_ROLLOVER = "UPGRADE_ROLLOVER"


class QuoteStatus(str, Enum):
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class DelinquencyEventType(str, Enum):
    GRACE_ENTERED = "GRACE_ENTERED"
    DELINQUENCY_ENTERED = "DELINQUENCY_ENTERED"
    DEFAULT_DECLARED = "DEFAULT_DECLARED"
    CURED = "CURED"
    LATE_FEE_ASSESSED = "LATE_FEE_ASSESSED"
    FINANCING_LOCK_APPLIED = "FINANCING_LOCK_APPLIED"
    FINANCING_LOCK_RELEASED = "FINANCING_LOCK_RELEASED"


# --- Entity shapes --------------------------------------------------------
# Resources carrying id + created_at + updated_at + version.

class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    mobile_number: str
    status: str
    financing_lock_reason: Optional[str]
    financing_locked_at: Optional[str]
    credit_score_band: Optional[str]
    credit_limit_cents: int
    outstanding_principal_cents: int
    open_loan_count: int
    completed_upgrade_count: int
    last_upgrade_completed_at: Optional[str]
    default_strike_count: int
    created_at: str
    updated_at: str
    version: int


class DeviceModel(TypedDict):
    id: str
    sku: str
    display_name: str
    retail_price_cents: int
    monthly_protection_premium_cents: int
    trade_in_base_credit_cents: int
    concurrent_reservation_capacity: int
    reserved_slot_count: int
    generation_year: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class CarrierAccount(TypedDict):
    id: str
    customer_id: str
    carrier_code: str
    account_number: str
    unlock_policy_days: int
    activation_state: str
    activated_at: Optional[str]
    port_freeze_flag: bool
    active_device_imei: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditApplication(TypedDict):
    id: str
    customer_id: str
    device_model_id: str
    requested_term_months: int
    declared_down_payment_cents: int
    requested_principal_cents: int
    credit_score_band: Optional[str]
    credit_limit_cents: int
    exposure_at_decision_cents: int
    approved_principal_cents: int
    conditional_down_payment_required_cents: int
    status: str
    decision_reason: Optional[str]
    underwriter_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstallmentLoan(TypedDict):
    id: str
    customer_id: str
    credit_application_id: str
    device_model_id: str
    predecessor_loan_id: Optional[str]
    down_payment_cents: int
    origination_fee_cents: int
    rolled_over_balance_cents: int
    principal_cents: int
    term_months: int
    monthly_protection_premium_cents: int
    premium_total_cents: int
    monthly_installment_cents: int
    paid_principal_cents: int
    paid_premium_cents: int
    outstanding_late_fee_cents: int
    paid_installment_count: int
    obligation_balance_cents: int
    status: str
    closure_reason: Optional[str]
    delinquency_state: str
    days_past_due: int
    protection_coverage_status: str
    upgrade_hold_flag: bool
    origination_date: str
    upgrade_window_opens_at: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    loan_id: str
    installment_number: int
    due_date: str
    principal_component_cents: int
    premium_component_cents: int
    amount_due_cents: int
    paid_principal_cents: int
    paid_premium_cents: int
    paid_amount_cents: int
    late_fee_cents: int
    late_fee_paid_cents: int
    late_fee_assessed: bool
    status: str
    paid_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeviceUnit(TypedDict):
    id: str
    loan_id: str
    device_model_id: str
    carrier_account_id: Optional[str]
    imei: str
    activation_status: str
    unlock_status: str
    possession_status: str
    activated_at: Optional[str]
    unlock_requested_at: Optional[str]
    unlocked_at: Optional[str]
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UpgradeRequest(TypedDict):
    id: str
    loan_id: str
    customer_id: str
    target_device_model_id: str
    new_loan_id: Optional[str]
    payoff_quote_id: Optional[str]
    fulfillment_window_start: str
    fulfillment_window_end: str
    paid_installment_count_at_request: int
    eligibility_ratio_bps: int
    trade_in_credit_projection_cents: int
    projected_rollover_balance_cents: int
    credit_shortfall_cents: int
    funding_flag: str
    status: str
    additional_down_payment_cents: int
    expiry_reason: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    upgrade_request_id: str
    device_unit_id: str
    declared_condition: str
    credit_estimate_cents: int
    graded_condition: Optional[str]
    credit_final_cents: Optional[int]
    diagnostic_result: Optional[str]
    latest_report_sequence_no: int
    credit_variance_cents: int
    dispute_count: int
    dispute_reason: Optional[str]
    status: str
    received_at: Optional[str]
    graded_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayoffQuote(TypedDict):
    id: str
    loan_id: str
    quote_type: str
    remaining_principal_cents: int
    outstanding_late_fee_cents: int
    unearned_premium_cents: int
    premium_rebate_cents: int
    admin_fee_cents: int
    total_payoff_cents: int
    past_due_amount_cents: int
    paid_installment_count_at_quote: int
    issued_at: str
    expires_at: str
    status: str
    consumed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only records: only id + created_at, never updated_at/version ---

class PaymentPosting(TypedDict):
    id: str
    loan_id: str
    posting_type: str
    reverses_posting_id: Optional[str]
    amount_cents: int
    allocated_late_fee_cents: int
    allocated_premium_cents: int
    allocated_principal_cents: int
    installments_satisfied_count: int
    overpayment_cents: int
    obligation_balance_after_cents: int
    posted_at: str
    created_at: str


class DiagnosticReport(TypedDict):
    id: str
    trade_in_id: str
    sequence_no: int
    report_type: str
    technician_user_id: str
    screen_grade: str
    battery_health_pct: int
    water_damage_flag: bool
    functional_pass: bool
    derived_condition: str
    condition_multiplier_bps: int
    battery_deduction_cents: int
    screen_deduction_cents: int
    computed_credit_cents: int
    diagnostic_result: str
    override_reason: Optional[str]
    created_at: str


class DelinquencyEvent(TypedDict):
    id: str
    loan_id: str
    event_type: str
    from_state: Optional[str]
    to_state: Optional[str]
    days_past_due_at_event: int
    amount_cents: int
    occurred_at: str
    created_at: str
