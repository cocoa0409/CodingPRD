"""Domain types: entity TypedDicts, status enums, role enum.

Every primary resource in this network carries the same four system-managed
properties (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    FREIGHT_AGENT = "FreightAgent"
    CAPACITY_OWNER_OPERATOR = "CapacityOwnerOperator"
    SAFETY_REVIEWER = "SafetyReviewer"
    SETTLEMENT_OPERATOR = "SettlementOperator"
    NETWORK_ADMINISTRATOR = "NetworkAdministrator"
    AGENT_MANAGER = "AgentManager"


# ─── Status enums ─────────────────────────────────────────────────────────────

class AgentStatus(str, Enum):
    PENDING_ENROLLMENT = "PENDING_ENROLLMENT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CapacityOwnerStatus(str, Enum):
    PENDING_QUALIFICATION = "PENDING_QUALIFICATION"
    QUALIFIED = "QUALIFIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    DECERTIFIED = "DECERTIFIED"


class QualificationPosture(str, Enum):
    QUALIFIED_CLEAR = "QUALIFIED_CLEAR"
    QUALIFICATION_RESTRICTED = "QUALIFICATION_RESTRICTED"
    QUALIFICATION_FROZEN = "QUALIFICATION_FROZEN"


class EquipmentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    PENDING_INSPECTION = "PENDING_INSPECTION"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class InspectionStatus(str, Enum):
    CURRENT = "CURRENT"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    RETIRED = "RETIRED"


class EquipmentType(str, Enum):
    TRACTOR = "TRACTOR"
    STRAIGHT_TRUCK = "STRAIGHT_TRUCK"
    VAN_TRAILER = "VAN_TRAILER"
    REEFER_TRAILER = "REEFER_TRAILER"
    FLATBED_TRAILER = "FLATBED_TRAILER"


class DocumentType(str, Enum):
    CDL = "CDL"
    MEDICAL_CARD = "MEDICAL_CARD"
    MVR_REPORT = "MVR_REPORT"
    DRUG_TEST = "DRUG_TEST"
    OA_ENROLLMENT = "OA_ENROLLMENT"
    LIABILITY_INSURANCE = "LIABILITY_INSURANCE"


class DocumentStatus(str, Enum):
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class ExclusivityStatus(str, Enum):
    OWNED_EXCLUSIVE = "OWNED_EXCLUSIVE"
    OPEN_SHARED = "OPEN_SHARED"
    RELEASED = "RELEASED"


class ReleasedReason(str, Enum):
    NON_SOLICITATION_BREACH = "NON_SOLICITATION_BREACH"
    AGENT_TERMINATED = "AGENT_TERMINATED"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"


class LoadStatus(str, Enum):
    POSTED = "POSTED"
    AWARDED = "AWARDED"
    COVERED = "COVERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class OfferStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class TripStatus(str, Enum):
    DISPATCH_PENDING = "DISPATCH_PENDING"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class SettlementMethod(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TransactionType(str, Enum):
    ADVANCE = "ADVANCE"
    ADVANCE_REPAYMENT = "ADVANCE_REPAYMENT"
    ESCROW_DEPOSIT = "ESCROW_DEPOSIT"
    ESCROW_RELEASE = "ESCROW_RELEASE"
    MAINTENANCE_DEPOSIT = "MAINTENANCE_DEPOSIT"
    MAINTENANCE_WITHDRAWAL = "MAINTENANCE_WITHDRAWAL"
    OA_PREMIUM_DEDUCTION = "OA_PREMIUM_DEDUCTION"
    INSURANCE_PREMIUM_DEDUCTION = "INSURANCE_PREMIUM_DEDUCTION"


class LedgerEntryStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


# ─── Entity TypedDicts (all carry the four common properties) ─────────────────

class Agent(TypedDict):
    id: str
    agent_code: str
    legal_name: str
    home_state: str
    commission_rate_pct: float
    territory_codes: List[str]
    customer_ownership_days: int
    status: str
    settlement_hold: bool
    active_customer_count: int
    awarded_load_count: int
    created_at: str
    updated_at: str
    version: int


class CapacityOwner(TypedDict):
    id: str
    owner_code: str
    legal_name: str
    home_terminal_city: str
    revenue_split_pct: float
    oa_enrolled: bool
    liability_insurance_deductible_cents: int
    escrow_balance_cents: int
    maintenance_balance_cents: int
    safety_score: int
    qualification_posture: str
    qualified_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    capacity_owner_id: str
    unit_number: str
    equipment_type: str
    model_year: int
    inspection_due_at: str
    inspection_passed_at: Optional[str]
    inspection_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceDocument(TypedDict):
    id: str
    capacity_owner_id: str
    document_type: str
    document_number: str
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict):
    id: str
    agent_id: str
    customer_ref: str
    shipper_name: str
    first_booked_at: str
    ownership_expires_at: str
    exclusivity_status: str
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Load(TypedDict):
    id: str
    agent_id: str
    awarded_capacity_owner_id: Optional[str]
    customer_ref: str
    origin_state: str
    destination_state: str
    linehaul_revenue_cents: int
    fuel_surcharge_cents: int
    accessorial_revenue_cents: int
    dispatched_miles: int
    board_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadOffer(TypedDict):
    id: str
    load_id: str
    capacity_owner_id: str
    offered_pay_cents: int
    owner_pay_ceiling_cents: int
    offered_at: str
    expires_at: str
    selected_rank: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    load_id: str
    capacity_owner_id: str
    equipment_id: str
    departed_at: str
    deadline_at: str
    delivered_at: Optional[str]
    actual_miles: Optional[int]
    proof_of_delivery_code: Optional[str]
    on_time: Optional[bool]
    maintenance_reserve_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    trip_id: str
    agent_id: str
    capacity_owner_id: str
    settlement_method: str
    commissionable_base_cents: Optional[int]
    linehaul_revenue_allocated_cents: Optional[int]
    fuel_surcharge_allocated_cents: Optional[int]
    accessorial_allocated_cents: Optional[int]
    agent_share_cents: Optional[int]
    owner_operator_share_cents: Optional[int]
    company_share_cents: Optional[int]
    oa_premium_cents: Optional[int]
    insurance_premium_cents: Optional[int]
    maintenance_withholding_cents: Optional[int]
    escrow_withholding_cents: Optional[int]
    advance_repayment_cents: Optional[int]
    net_owner_operator_pay_cents: Optional[int]
    net_agent_pay_cents: Optional[int]
    settled_total_cents: Optional[int]
    variant_delta_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class EscrowTransaction(TypedDict):
    id: str
    capacity_owner_id: str
    transaction_type: str
    amount_cents: int
    effective_at: str
    reverses_transaction_id: Optional[str]
    status: str
    resulting_escrow_balance_cents: int
    resulting_maintenance_balance_cents: int
    created_at: str
    updated_at: str
    version: int


# ─── Test-driving capability payload shapes ───────────────────────────────────

class AdvancePostResult(TypedDict):
    advance_transaction_id: str
    escrow_balance_cents: int
    outstanding_advance_cents: int


class PeriodCloseResult(TypedDict):
    period_month: str
    eligible_load_count: int
    paid_load_count: int
    per_load_fee_cents: int
    period_fee_cents: int
    effective_per_load_fee_cents: int


class PerLoadTierResult(TypedDict):
    tier_load_count: int
    marginal_fee_cents: int
    cumulative_fee_cents: int
    effective_per_load_fee_cents: int
    month_start: str
    month_end: str