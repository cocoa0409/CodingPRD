"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    HOMEOWNER = "Homeowner"
    WARRANTY_REP = "WarrantyRep"
    TRADE_PARTNER = "TradePartner"
    WARRANTY_MANAGER = "WarrantyManager"
    FINANCE_ADMIN = "FinanceAdmin"
    WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"


class WarrantyProgram(str, Enum):
    STANDARD = "STANDARD"
    THIRD_PARTY_ADMINISTERED = "THIRD_PARTY_ADMINISTERED"


class ItemCategory(str, Enum):
    DRYWALL_PAINT = "DRYWALL_PAINT"
    FLOORING = "FLOORING"
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    FOUNDATION = "FOUNDATION"
    FRAMING = "FRAMING"
    LANDSCAPING = "LANDSCAPING"
    APPLIANCE = "APPLIANCE"
    ROUTINE_MAINTENANCE = "ROUTINE_MAINTENANCE"


class Severity(str, Enum):
    EMERGENCY = "EMERGENCY"
    URGENT = "URGENT"
    STANDARD = "STANDARD"


class ServiceRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPROVED = "APPROVED"
    IN_SERVICE = "IN_SERVICE"
    PENDING_FOLLOWUP = "PENDING_FOLLOWUP"
    CLOSED = "CLOSED"
    DENIED = "DENIED"
    DISPUTED = "DISPUTED"
    REOPENED = "REOPENED"


class DeterminedTier(str, Enum):
    WORKMANSHIP = "WORKMANSHIP"
    SYSTEMS = "SYSTEMS"
    STRUCTURAL = "STRUCTURAL"


class DenialReasonCode(str, Enum):
    OUT_OF_TERM = "OUT_OF_TERM"
    EXCLUDED_CATEGORY = "EXCLUDED_CATEGORY"
    HOMEOWNER_CAUSED = "HOMEOWNER_CAUSED"
    NORMAL_MAINTENANCE = "NORMAL_MAINTENANCE"


class DisputeOutcome(str, Enum):
    BUILDER_UPHELD = "BUILDER_UPHELD"
    HOMEOWNER_PREVAILS = "HOMEOWNER_PREVAILS"
    SETTLED = "SETTLED"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DefectResponsibility(str, Enum):
    SUBCONTRACTOR = "SUBCONTRACTOR"
    BUILDER = "BUILDER"
    HOMEOWNER = "HOMEOWNER"


class Trade(str, Enum):
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    DRYWALL = "DRYWALL"
    FLOORING = "FLOORING"
    GENERAL = "GENERAL"


class ChargebackStatus(str, Enum):
    ISSUED = "ISSUED"
    APPROVED = "APPROVED"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    REDUCED = "REDUCED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    VOID = "VOID"


class AmountBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ReserveEntryKind(str, Enum):
    ACCRUAL = "ACCRUAL"
    TRUE_UP = "TRUE_UP"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    DRAW = "DRAW"
    RECOVERY = "RECOVERY"


class AlertStatus(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    DEPLETED = "DEPLETED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"


class Homeowner(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Home(TypedDict, total=False):
    id: str
    homeowner_id: str
    lot_number: str
    community_name: str
    sale_price_cents: int
    closing_date: str
    warranty_program: str
    workmanship_end_date: str
    systems_end_date: str
    structural_end_date: str
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict, total=False):
    id: str
    home_id: str
    homeowner_id: str
    item_category: str
    severity: str
    description: str
    reported_at: str
    status: str
    determined_tier: Optional[str]
    denied_at: Optional[str]
    denial_reason_code: Optional[str]
    education_packet_code: Optional[str]
    dispute_reason: Optional[str]
    dispute_outcome: Optional[str]
    dispute_deadline_at: Optional[str]
    approved_at: Optional[str]
    response_due_at: str
    completion_due_at: Optional[str]
    response_breached: bool
    completion_breached: bool
    escalation_level: int
    actual_cost_cents: int
    followup_entered_at: Optional[str]
    satisfaction_score: Optional[int]
    closed_at: Optional[str]
    reopened_count: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    service_request_id: str
    trade_partner_id: str
    window_start: str
    window_end: str
    duration_minutes: int
    estimated_cost_cents: int
    defect_responsibility: str
    actual_cost_cents: Optional[int]
    status: str
    completed_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradePartner(TypedDict, total=False):
    id: str
    company_name: str
    trade: str
    contact_email: str
    daily_capacity_minutes: int
    outstanding_chargeback_cents: int
    open_work_order_count: int
    created_at: str
    updated_at: str
    version: int


class Chargeback(TypedDict, total=False):
    id: str
    work_order_id: str
    trade_partner_id: str
    status: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    amount_basis: str
    payable_amount_cents: int
    collected_cents: int
    outstanding_cents: int
    issued_at: str
    contest_deadline_at: str
    contest_reason: Optional[str]
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyReserve(TypedDict, total=False):
    id: str
    home_id: str
    expected_lifetime_accrual_cents: int
    accrued_to_date_cents: int
    drawn_to_date_cents: int
    recovered_to_date_cents: int
    balance_cents: int
    last_accrual_month_index: int
    alert_status: str
    created_at: str
    updated_at: str
    version: int


# Ledger lines are append-only (PRD §2.5): they carry ONLY id and created_at;
# updated_at and version are absent by contract.
class ReserveEntry(TypedDict, total=False):
    id: str
    created_at: str
    reserve_id: str
    kind: str
    amount_cents: int
    month_index: Optional[int]
    work_order_ref: Optional[str]
    chargeback_ref: Optional[str]
    claim_ref: Optional[str]
    note: Optional[str]


class AdministratorClaim(TypedDict, total=False):
    id: str
    service_request_id: str
    home_id: str
    claimed_amount_cents: int
    external_reference: Optional[str]
    status: str
    approved_amount_cents: Optional[int]
    denial_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
