"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER_SERVICE = "CustomerService"
    CREDIT_ANALYST = "CreditAnalyst"
    TRADE_IN_INSPECTOR = "TradeInInspector"
    CUSTOMER = "Customer"


class AccountType(str, Enum):
    FAMILY = "FAMILY"
    BUSINESS = "BUSINESS"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CreditClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"
    CLASS_D = "CLASS_D"
    BLOCKED = "BLOCKED"


class BillingMode(str, Enum):
    PREPAID = "PREPAID"
    POSTPAID = "POSTPAID"


class ServiceStatus(str, Enum):
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class NumberStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    RESERVED = "RESERVED"
    PORTED_IN = "PORTED_IN"
    ASSIGNED = "ASSIGNED"
    RECLAIMED = "RECLAIMED"


class PortProtectionStatus(str, Enum):
    UNPROTECTED = "UNPROTECTED"
    PROTECTED = "PROTECTED"


class PromoEligibilityState(str, Enum):
    INELIGIBLE = "INELIGIBLE"
    PROVISIONAL_ELIGIBLE = "PROVISIONAL_ELIGIBLE"
    VESTED = "VESTED"
    CLAWED_BACK = "CLAWED_BACK"


class PortRequestState(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    RESUBMITTED = "RESUBMITTED"
    ACCEPTED_PENDING_CUTOVER = "ACCEPTED_PENDING_CUTOVER"
    PORTED = "PORTED"
    CANCELLED = "CANCELLED"


class PromoScheduleState(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    VESTED = "VESTED"
    CLAWED_BACK = "CLAWED_BACK"


class DevicePlanState(str, Enum):
    QUOTED = "QUOTED"
    ACTIVE = "ACTIVE"
    UPGRADE_ELIGIBLE = "UPGRADE_ELIGIBLE"
    CONVERTED = "CONVERTED"


class TradeCondition(str, Enum):
    FLAWLESS = "FLAWLESS"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    BROKEN = "BROKEN"


class AssessmentState(str, Enum):
    SUBMITTED = "SUBMITTED"
    GRADED = "GRADED"


class ReservationState(str, Enum):
    HELD = "HELD"
    COMMITTED = "COMMITTED"
    EXPIRED = "EXPIRED"


class MigrationState(str, Enum):
    DRAFT = "DRAFT"
    ELIGIBILITY_CHECK = "ELIGIBILITY_CHECK"
    BLOCKED = "BLOCKED"
    APPROVED = "APPROVED"
    CUTOVER_SCHEDULED = "CUTOVER_SCHEDULED"
    CUTOVER_COMPLETE = "CUTOVER_COMPLETE"


class LineAdditionState(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class CaseState(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"
    DENIED = "DENIED"


class ProtectionType(str, Enum):
    ACCOUNT_PIN = "ACCOUNT_PIN"
    PORT_FREEZE = "PORT_FREEZE"
    FRAUD_HOLD = "FRAUD_HOLD"


class RequiresActionBy(str, Enum):
    CUSTOMER = "CUSTOMER"
    LOSING_CARRIER = "LOSING_CARRIER"
    GAINING_CARRIER = "GAINING_CARRIER"


class Account(TypedDict):
    """Top-level resource; carries id + created_at + updated_at + version."""

    id: str
    account_type: str
    account_status: str
    tax_id_last4: str
    credit_class: str
    payment_history_score: int
    active_line_count: int
    reserved_mdn_count: int
    deposit_required_cents: int
    existing_deposit_cents: int
    promo_credited_cents: int
    promo_clawed_back_cents: int
    net_promo_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class SubscriberLine(TypedDict):
    """Top-level resource; carries id + created_at + updated_at + version."""

    id: str
    account_id: str
    mdn: str
    billing_mode: str
    service_status: str
    number_status: str
    port_protection_status: str
    line_opened_at: str
    loyalty_tenure_months: int
    retention_cycle_count: int
    promo_eligibility_state: str
    cancellation_effective_at: str
    created_at: str
    updated_at: str
    version: int


class PortRequest(TypedDict):
    """Top-level resource; carries id + created_at + updated_at + version."""

    id: str
    subscriber_line_id: str
    losing_carrier_code: str
    account_number_at_losing_carrier: str
    transfer_pin: str
    requested_cutover_at: str
    request_state: str
    rejection_count: int
    last_rejection_code: str
    rejections: List[dict]
    last_rejection_at: str
    submitted_at: str
    supersedes_port_request_id: str
    cutover_completed_at: str
    created_at: str
    updated_at: str
    version: int


class PromoCreditSchedule(TypedDict):
    """Top-level resource; carries id + created_at + updated_at + version."""

    id: str
    subscriber_line_id: str
    promo_code: str
    monthly_credit_cents: int
    installment_months: int
    retention_requirement_cycles: int
    schedule_state: str
    window_start: str
    window_end: str
    provisional_total_cents: int
    vested_total_cents: int
    cycles_elapsed: int
    created_at: str
    updated_at: str
    version: int


class DeviceInstallmentPlan(TypedDict):
    """Top-level resource; carries id + created_at + updated_at + version."""

    id: str
    subscriber_line_id: str
    device_model: str
    device_price_cents: int
    down_payment_cents: int
    installment_months: int
    monthly_installment_cents: int
    remaining_balance_cents: int
    plan_state: str
    financed_at: str
    upgrade_eligible_at: str
    trade_in_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class TradeInAssessment(TypedDict):
    """Top-level resource; carries id + created_at + updated_at + version."""

    id: str
    installment_plan_id: str
    parent_plan_id: str
    device_model: str
    declared_condition: str
    graded_condition: str
    assessment_state: str
    estimated_credit_cents: int
    final_credit_cents: int
    grade_delta_cents: int
    submitted_at: str
    graded_at: str
    created_at: str
    updated_at: str
    version: int


class NumberReservation(TypedDict):
    """Top-level resource; carries id + created_at + updated_at + version."""

    id: str
    account_id: str
    mdn: str
    pool_code: str
    reservation_state: str
    reserved_at: str
    reserved_until: str
    hold_days: int
    committed_line_id: str
    created_at: str
    updated_at: str
    version: int


class MigrationRequest(TypedDict):
    """Top-level resource; carries id + created_at + updated_at + version."""

    id: str
    subscriber_line_id: str
    source_billing_mode: str
    target_billing_mode: str
    migration_state: str
    carried_mdn: str
    prepaid_balance_cents: int
    device_balance_cents: int
    proration_credit_cents: int
    requested_cutover_at: str
    cutover_completed_at: str
    created_at: str
    updated_at: str
    version: int


class LineAdditionRequest(TypedDict):
    """Top-level resource; carries id + created_at + updated_at + version."""

    id: str
    account_id: str
    parent_account_id: str
    line_count: int
    requested_mdn: str
    determined_credit_class: str
    required_deposit_cents: int
    request_state: str
    decision_note: str
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class PortProtectionCase(TypedDict):
    """Top-level resource; carries id + created_at + updated_at + version."""

    id: str
    subscriber_line_id: str
    protection_type: str
    verified_identity: bool
    case_state: str
    set_at: str
    cleared_at: str
    reason_code: str
    created_at: str
    updated_at: str
    version: int


class RejectionCodeCatalog(TypedDict):
    """Static reference table: carries ONLY id and created_at.

    This resource deliberately has neither updated_at nor version.
    """

    id: str
    rejection_code: str
    description: str
    guidance_text: str
    resubmission_allowed: bool
    retry_after_hours: int
    requires_action_by: str
    created_at: str


class SystemConfig(TypedDict):
    """Single system configuration row; carries id + created_at + updated_at + version."""

    id: str
    ops_run_epoch: int
    last_ops_run_at: str
    last_line_cancellation_deadline: str
    line_cancellation_grace_hours: int
    promo_window_buffer_days: int
    created_at: str
    updated_at: str
    version: int