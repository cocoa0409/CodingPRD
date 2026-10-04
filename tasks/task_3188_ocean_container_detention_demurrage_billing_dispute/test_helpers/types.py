"""Domain types: entity TypedDicts, status enums, role enum for the Ocean Billing API."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CONTRACT_MANAGER = "ContractManager"
    TERMINAL_OPERATOR = "TerminalOperator"
    EQUIPMENT_CONTROLLER = "EquipmentController"
    BILLING_AGENT = "BillingAgent"
    CREDIT_SUPERVISOR = "CreditSupervisor"
    CREDIT_DIRECTOR = "CreditDirector"
    CUSTOMER_REP = "CustomerRep"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    RELEASED = "RELEASED"


class ReturnLocationStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class ContainerStatus(str, Enum):
    DISCHARGED = "DISCHARGED"
    AVAILABLE = "AVAILABLE"
    GATE_OUT = "GATE_OUT"
    EMPTY_RETURNED = "EMPTY_RETURNED"
    BILLED = "BILLED"


class EquipmentType(str, Enum):
    DRY20 = "DRY20"
    DRY40 = "DRY40"
    DRY40HC = "DRY40HC"
    REEFER40 = "REEFER40"
    FLATRACK40 = "FLATRACK40"


class RateSchedule(str, Enum):
    STANDARD = "STANDARD"
    EXTENDED_TIERED = "EXTENDED_TIERED"


class ChargeKind(str, Enum):
    DEMURRAGE = "DEMURRAGE"
    DETENTION = "DETENTION"


class HoldCode(str, Enum):
    CUSTOMS_HOLD = "CUSTOMS_HOLD"
    CHASSIS_SHORTAGE = "CHASSIS_SHORTAGE"
    USDA_HOLD = "USDA_HOLD"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    DAYS_1_30 = "DAYS_1_30"
    DAYS_31_60 = "DAYS_31_60"
    DAYS_61_PLUS = "DAYS_61_PLUS"


class DisputeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_FULL_CREDIT = "RESOLVED_FULL_CREDIT"
    RESOLVED_PARTIAL_CREDIT = "RESOLVED_PARTIAL_CREDIT"
    RESOLVED_DENIED = "RESOLVED_DENIED"
    WITHDRAWN = "WITHDRAWN"


class DisputeReason(str, Enum):
    APPOINTMENT_UNAVAILABLE = "APPOINTMENT_UNAVAILABLE"
    CHASSIS_SHORTAGE = "CHASSIS_SHORTAGE"
    CUSTOMS_HOLD = "CUSTOMS_HOLD"
    FREE_TIME_MISCALC = "FREE_TIME_MISCALC"
    RATE_MISMATCH = "RATE_MISMATCH"
    OTHER = "OTHER"


class EvidenceType(str, Enum):
    APPOINTMENT_SCREENSHOT = "APPOINTMENT_SCREENSHOT"
    CHASSIS_POOL_NOTICE = "CHASSIS_POOL_NOTICE"
    CUSTOMS_HOLD_NOTICE = "CUSTOMS_HOLD_NOTICE"
    APPOINTMENT_API_LOG = "APPOINTMENT_API_LOG"
    OTHER = "OTHER"


class ResolutionCode(str, Enum):
    FULL_CREDIT = "FULL_CREDIT"
    PARTIAL_CREDIT = "PARTIAL_CREDIT"
    DENIED = "DENIED"


class WaiverStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class AuthorityTier(str, Enum):
    TIER_1_AGENT = "TIER_1_AGENT"
    TIER_2_SUPERVISOR = "TIER_2_SUPERVISOR"
    TIER_3_DIRECTOR = "TIER_3_DIRECTOR"


class PaymentStatus(str, Enum):
    SETTLED = "SETTLED"


class HoldEntry(TypedDict, total=False):
    code: str
    placed_ts: str
    released_ts: Optional[str]


class CustomerAccount(TypedDict):
    id: str
    account_code: str
    legal_name: str
    credit_hold: bool
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    customer_account_id: str
    contract_ref: str
    demurrage_free_days: int
    detention_free_days: int
    saturday_counts_as_free_day: bool
    demurrage_rate_schedule: str
    detention_rate_schedule: str
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Terminal(TypedDict):
    id: str
    terminal_code: str
    timezone: str
    daily_appointment_capacity: int
    gate_closed_weekends: bool
    created_at: str
    updated_at: str
    version: int


class TerminalHoliday(TypedDict, total=False):
    # Append-only ledger fact: carries ONLY id + created_at (no updated_at, no version)
    id: str
    terminal_id: str
    holiday_date: str
    name: str
    created_at: str


class TerminalAppointmentSlot(TypedDict):
    id: str
    terminal_id: str
    slot_date: str
    slot_seq: int
    capacity: int
    booked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentReturnLocation(TypedDict):
    id: str
    location_code: str
    terminal_id: str
    accepts_equipment_types: List[str]
    daily_empty_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict):
    id: str
    container_number: str
    equipment_type: str
    customer_account_id: str
    service_contract_id: str
    terminal_id: str
    discharge_ts: str
    available_ts: str
    gate_out_ts: Optional[str]
    empty_return_ts: Optional[str]
    assigned_return_location_id: Optional[str]
    hold_flags: List[HoldEntry]
    demurrage_billable_days: int
    detention_billable_days: int
    demurrage_amount_cents: int
    detention_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargeAccrual(TypedDict, total=False):
    # Append-only ledger fact: carries ONLY id + created_at (no updated_at, no version)
    id: str
    container_id: str
    charge_kind: str
    billable_days: int
    amount_cents: int
    rate_schedule: str
    computed_at: str
    window_from: str
    window_to: str
    voided: bool
    created_at: str


class Invoice(TypedDict):
    id: str
    customer_account_id: str
    container_id: str
    demurrage_total_cents: int
    detention_total_cents: int
    gross_amount_cents: int
    credit_total_cents: int
    paid_total_cents: int
    balance_due_cents: int
    issued_at: str
    due_at: str
    aging_bucket: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    invoice_id: str
    filed_by_account_id: str
    dispute_reason: str
    contested_amount_cents: int
    evidence_window_start: str
    evidence_window_end: str
    evidence_summary: str
    resolution_code: Optional[str]
    resolved_amount_cents: int
    resolution_justification: Optional[str]
    submitted_at: str
    sla_due_at: str
    escalated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DisputeEvidence(TypedDict, total=False):
    # Append-only ledger fact: carries ONLY id + created_at (no updated_at, no version)
    id: str
    dispute_id: str
    evidence_type: str
    evidence_date: str
    reference_uri: str
    supersedes_evidence_id: Optional[str]
    created_at: str


class CreditWaiver(TypedDict):
    id: str
    invoice_id: str
    dispute_id: Optional[str]
    amount_cents: int
    authority_tier: str
    justification: str
    applied_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    # Append-only ledger fact: carries ONLY id + created_at (no updated_at, no version)
    id: str
    invoice_id: str
    amount_cents: int
    tendered_at: str
    status: str
    created_at: str
