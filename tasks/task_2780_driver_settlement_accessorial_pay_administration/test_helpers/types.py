"""Domain types for the driver settlement and accessorial pay API.

Entity shapes, status enumerations and the role enumeration, all named exactly as
the specification under test names them. The enumerations are plain string
constants so that a value is safe to place in a JSON body and in a query string
alike.
"""
from typing import Optional, TypedDict


class UserRole:
    PAYROLL_ADMIN = "PayrollAdmin"
    SETTLEMENT_CLERK = "SettlementClerk"
    SETTLEMENT_APPROVER = "SettlementApprover"
    DRIVER = "Driver"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


# ─── Value enumerations ───────────────────────────────

class DriverType:
    COMPANY_SOLO = "COMPANY_SOLO"
    COMPANY_TEAM = "COMPANY_TEAM"
    OWNER_OPERATOR = "OWNER_OPERATOR"
    LEASED_OPERATOR = "LEASED_OPERATOR"


class MileageGuide:
    PRACTICAL = "PRACTICAL"
    HHG = "HHG"


class PerDiemMethod:
    NONE = "NONE"
    DAY_BASED = "DAY_BASED"
    PERCENT_OF_LINEHAUL = "PERCENT_OF_LINEHAUL"


class ComponentType:
    PER_MILE = "PER_MILE"
    REVENUE_PERCENT = "REVENUE_PERCENT"
    HOURLY = "HOURLY"
    ACTIVITY = "ACTIVITY"


class RateUnit:
    MILE = "MILE"
    PERCENT_BPS = "PERCENT_BPS"
    HOUR = "HOUR"
    LOAD = "LOAD"


class AccessorialType:
    DETENTION = "DETENTION"
    LAYOVER = "LAYOVER"
    STOP_OFF = "STOP_OFF"
    TARPING = "TARPING"
    BREAKDOWN = "BREAKDOWN"


class RejectReasonCode:
    NOT_SUPPORTED_BY_LOG = "NOT_SUPPORTED_BY_LOG"
    SHIPPER_NOT_LIABLE = "SHIPPER_NOT_LIABLE"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    OUTSIDE_POLICY = "OUTSIDE_POLICY"


class AdvanceType:
    CASH_ADVANCE = "CASH_ADVANCE"
    FUEL_CARD = "FUEL_CARD"


class EscrowTxnType:
    DEPOSIT = "DEPOSIT"
    PERMISSIBLE_DEDUCTION = "PERMISSIBLE_DEDUCTION"
    REVERSAL = "REVERSAL"
    RETURN_DISBURSEMENT = "RETURN_DISBURSEMENT"


class EscrowReasonCode:
    SETTLEMENT_ACCRUAL = "SETTLEMENT_ACCRUAL"
    SETTLEMENT_VOID = "SETTLEMENT_VOID"
    TERMINATION_RETURN = "TERMINATION_RETURN"
    DEDUCTION_DISPUTED = "DEDUCTION_DISPUTED"
    ESCROW_FUNDING = "ESCROW_FUNDING"
    TRACTOR_LEASE = "TRACTOR_LEASE"
    INSURANCE_PREMIUM = "INSURANCE_PREMIUM"
    PERMIT_FEE = "PERMIT_FEE"
    CARGO_CLAIM_DAMAGE = "CARGO_CLAIM_DAMAGE"
    FUEL_TAX_TRUEUP = "FUEL_TAX_TRUEUP"
    ADVANCE_DEFAULT = "ADVANCE_DEFAULT"
    EQUIPMENT_DAMAGE = "EQUIPMENT_DAMAGE"
    UNRETURNED_EQUIPMENT = "UNRETURNED_EQUIPMENT"
    FUEL_CARD_DEFAULT = "FUEL_CARD_DEFAULT"


class LineType:
    LINEHAUL_PER_MILE = "LINEHAUL_PER_MILE"
    LINEHAUL_PERCENT = "LINEHAUL_PERCENT"
    HOURLY = "HOURLY"
    ACTIVITY = "ACTIVITY"
    ACCESSORIAL = "ACCESSORIAL"
    RETRO_CORRECTION = "RETRO_CORRECTION"
    PER_DIEM = "PER_DIEM"
    ESCROW_DEDUCTION = "ESCROW_DEDUCTION"
    ADVANCE_RECOVERY = "ADVANCE_RECOVERY"


class ReferenceType:
    LOAD = "LOAD"
    ACCESSORIAL_CLAIM = "ACCESSORIAL_CLAIM"
    ADVANCE = "ADVANCE"
    RETRO_CORRECTION = "RETRO_CORRECTION"
    DRIVER = "DRIVER"


class DisputeKind:
    MILEAGE = "MILEAGE"
    PAY = "PAY"


class VoidReasonCode:
    CLERICAL_ERROR = "CLERICAL_ERROR"
    WRONG_PERIOD = "WRONG_PERIOD"
    DISPUTE_RESOLUTION = "DISPUTE_RESOLUTION"
    DUPLICATE_SETTLEMENT = "DUPLICATE_SETTLEMENT"


class CorrectionType:
    MILEAGE_REGRADE = "MILEAGE_REGRADE"
    PAY_ADJUSTMENT = "PAY_ADJUSTMENT"


class CorrectionReasonCode:
    MILEAGE_GUIDE_REGRADE = "MILEAGE_GUIDE_REGRADE"
    MILEAGE_DISPUTE_UPHELD = "MILEAGE_DISPUTE_UPHELD"
    PAY_DISPUTE_UPHELD = "PAY_DISPUTE_UPHELD"


# ─── Status enumerations ──────────────────────────────

class PayPackageStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EmploymentStatus:
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EscrowStatus:
    NOT_REQUIRED = "NOT_REQUIRED"
    COLLECTING = "COLLECTING"
    FUNDED = "FUNDED"
    CLOSING = "CLOSING"
    RETURNED = "RETURNED"


class MovementStatus:
    TENDERED = "TENDERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class PayStatus:
    UNPAID = "UNPAID"
    ACCRUED = "ACCRUED"
    SETTLED = "SETTLED"
    ADJUSTED = "ADJUSTED"


class ClaimStatus:
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class AdvanceStatus:
    ISSUED = "ISSUED"
    RECOVERING = "RECOVERING"
    RECOVERED = "RECOVERED"
    CANCELLED = "CANCELLED"


class SettlementStatus:
    DRAFT = "DRAFT"
    PREPARED = "PREPARED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class DisputeStatus:
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class CorrectionStatus:
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    CANCELLED = "CANCELLED"


# ─── Entity shapes ────────────────────────────────────
# Mutable records carry id, created_at, updated_at and version.
# Append-only logs (PayComponent, EscrowTransaction, SettlementLine) carry only
# id and created_at.

class PayPackage(TypedDict):
    id: str
    name: str
    driver_type: str
    mileage_guide: str
    per_diem_method: str
    escrow_required: bool
    escrow_target_cents: int
    escrow_monthly_deduction_cents: int
    status: str
    supersedes_pay_package_id: Optional[str]
    has_pending_revision: bool
    activated_at: Optional[str]
    retired_at: Optional[str]
    component_count: int
    created_at: str
    updated_at: str
    version: int


class PayComponent(TypedDict):
    id: str
    pay_package_id: str
    component_type: str
    unit: str
    rate_value: int
    taxable: bool
    sequence: int
    created_at: str


class Driver(TypedDict):
    id: str
    legal_name: str
    driver_type: str
    pay_package_id: Optional[str]
    home_state: Optional[str]
    per_diem_elected: bool
    employment_status: str
    terminated_at: Optional[str]
    escrow_status: str
    escrow_target_cents: int
    escrow_monthly_deduction_cents: int
    escrow_balance_cents: int
    escrow_funded_at: Optional[str]
    escrow_return_due_at: Optional[str]
    escrow_returned_at: Optional[str]
    pending_retro_correction_cents: int
    settlement_hold: bool
    ytd_gross_pay_cents: int
    ytd_taxable_wages_cents: int
    ytd_per_diem_non_taxable_cents: int
    advance_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class EscrowTransaction(TypedDict):
    id: str
    driver_id: str
    settlement_id: Optional[str]
    reverses_transaction_id: Optional[str]
    txn_type: str
    amount_cents: int
    reason_code: str
    document_ref: Optional[str]
    recorded_by_user_id: str
    balance_after_cents: int
    created_at: str


class Load(TypedDict):
    id: str
    driver_id: str
    settlement_id: Optional[str]
    pay_package_id_snapshot: Optional[str]
    origin_zip: Optional[str]
    dest_zip: Optional[str]
    linehaul_revenue_cents: int
    practical_miles: int
    hhg_miles: int
    stop_count: int
    hours_worked_minutes: int
    tarp_required: bool
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    movement_status: str
    pay_status: str
    applied_mileage_guide: Optional[str]
    base_guide_miles: Optional[int]
    paid_miles: Optional[int]
    short_haul_floor_applied: Optional[bool]
    linehaul_pay_cents: Optional[int]
    linehaul_line_type: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessorialClaim(TypedDict):
    id: str
    load_id: str
    driver_id: str
    settlement_id: Optional[str]
    accessorial_type: str
    start_at: str
    end_at: str
    document_ref: Optional[str]
    documentation_required: bool
    billable_units: int
    amount_cents: int
    status: str
    reject_reason_code: Optional[str]
    submitted_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Advance(TypedDict):
    id: str
    driver_id: str
    advance_type: str
    amount_cents: int
    installment_cents: Optional[int]
    recovered_cents: int
    outstanding_cents: int
    status: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    driver_id: str
    period_start: str
    period_end: str
    status: str
    prepared_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    prepared_at: Optional[str]
    approved_at: Optional[str]
    paid_at: Optional[str]
    voided_at: Optional[str]
    payment_reference: Optional[str]
    void_reason_code: Optional[str]
    itemization_required: bool
    line_count: int
    linehaul_total_cents: int
    accessorial_total_cents: int
    retro_correction_total_cents: int
    gross_pay_cents: int
    days_out_count: int
    per_diem_non_taxable_cents: int
    per_diem_excess_taxable_cents: int
    taxable_wages_cents: int
    escrow_deduction_cents: int
    advance_recovery_cents: int
    deduction_total_cents: int
    net_pay_cents: int
    created_at: str
    updated_at: str
    version: int


class SettlementLine(TypedDict):
    id: str
    settlement_id: str
    line_type: str
    reference_type: str
    reference_id: Optional[str]
    quantity: Optional[float]
    rate_value: Optional[int]
    amount_cents: int
    taxable: bool
    sequence: int
    created_at: str


class Dispute(TypedDict):
    id: str
    dispute_kind: str
    driver_id: str
    load_id: Optional[str]
    settlement_id: Optional[str]
    claimed_guide: Optional[str]
    claimed_miles: Optional[int]
    claimed_amount_cents: Optional[int]
    disputed_line_type: Optional[str]
    evidence_doc_ref: Optional[str]
    narrative: str
    status: str
    reopen_count: int
    resolution_note: Optional[str]
    resolution_correction_id: Optional[str]
    adjustment_cents: Optional[int]
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetroCorrection(TypedDict):
    id: str
    driver_id: str
    origin_settlement_id: Optional[str]
    applied_settlement_id: Optional[str]
    source_load_id: Optional[str]
    source_dispute_id: Optional[str]
    correction_type: str
    delta_gross_cents: int
    delta_taxable_cents: int
    reason_code: str
    status: str
    applied_at: Optional[str]
    cancelled_at: Optional[str]
    cancelled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
