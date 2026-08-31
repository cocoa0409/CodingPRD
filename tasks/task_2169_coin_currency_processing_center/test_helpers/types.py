"""Domain types for the Coin & Currency Processing Center API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    VAULT_MANAGER = "VaultManager"
    VAULT_TELLER = "VaultTeller"
    ARMORED_CARRIER = "ArmoredCarrier"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMER_ACCOUNT_HOLDER = "CustomerAccountHolder"
    FEDERAL_RESERVE_AGENT = "FederalReserveAgent"


# ─── Enumerations ─────────────────────────────────────────────────────────

class VaultPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class CoinDenomination(str, Enum):
    PENNY = "PENNY"
    NICKEL = "NICKEL"
    DIME = "DIME"
    QUARTER = "QUARTER"


class CustomerTier(str, Enum):
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    WATCH = "WATCH"


class CustomerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RiskGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class DepositTicketStatus(str, Enum):
    INTAKE = "INTAKE"
    VERIFIED = "VERIFIED"
    PROVISIONAL_CREDITED = "PROVISIONAL_CREDITED"
    HELD = "HELD"
    SETTLEMENT_READY = "SETTLEMENT_READY"
    SETTLED = "SETTLED"


class BagType(str, Enum):
    CURRENCY = "CURRENCY"
    COIN = "COIN"
    MIXED = "MIXED"


class CustodyStatus(str, Enum):
    SEALED = "SEALED"
    IN_TRANSIT = "IN_TRANSIT"
    VAULT_RECEIVED = "VAULT_RECEIVED"
    OPENED = "OPENED"


class CountStatus(str, Enum):
    PENDING = "PENDING"
    COUNTING = "COUNTING"
    COUNTED = "COUNTED"
    ADJUSTED = "ADJUSTED"


class CustodyEventType(str, Enum):
    PICKUP = "PICKUP"
    TRANSFER = "TRANSFER"
    VAULT_RECEIPT = "VAULT_RECEIPT"
    OPEN = "OPEN"


class MachineType(str, Enum):
    CURRENCY_SORTER = "CURRENCY_SORTER"
    COIN_COUNTER = "COIN_COUNTER"
    MIXED_PROCESSOR = "MIXED_PROCESSOR"


class MachineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class CountSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class FitnessLotCategory(str, Enum):
    FIT = "FIT"
    UNFIT = "UNFIT"
    COUNTERFEIT_SUSPECT = "COUNTERFEIT_SUSPECT"


class FitnessLotStatus(str, Enum):
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    PENDING_REVIEW = "PENDING_REVIEW"
    ATTACHED = "ATTACHED"
    DEPOSITED = "DEPOSITED"
    SEIZED = "SEIZED"


class CounterfeitReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ClaimType(str, Enum):
    COUNT_VARIANCE = "COUNT_VARIANCE"
    STATEMENT_ADJUSTMENT = "STATEMENT_ADJUSTMENT"


class DiscrepancyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class FedDepositStatus(str, Enum):
    PREPARED = "PREPARED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    CONFIRMED_WITH_ADJUSTMENT = "CONFIRMED_WITH_ADJUSTMENT"


class CoinOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED_FULL = "APPROVED_FULL"
    APPROVED_PARTIAL = "APPROVED_PARTIAL"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"
    RETURNED = "RETURNED"


# ─── Entity shapes ────────────────────────────────────────────────────────
# Resources carrying the full common set (id, created_at, updated_at, version).

class Vault(TypedDict):
    id: str
    vault_code: str
    name: str
    posture: str
    pickup_concurrency_limit: int
    cash_letter_adjustment_cents: int
    coin_face_value_on_hand_cents: int
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict):
    id: str
    account_number: str
    customer_name: str
    tier: str
    status: str
    ledger_balance_cents: int
    provisional_credit_cents: int
    available_balance_cents: int
    risk_score: float
    risk_grade: str
    denied_claim_count: int
    counterfeit_incident_count: int
    hold_count: int
    created_at: str
    updated_at: str
    version: int


class DepositTicket(TypedDict):
    id: str
    customer_account_id: str
    vault_id: str
    courier_manifest_number: str
    carrier_courier_user_id: str
    declared_bag_count: int
    status: str
    declared_total_cents: int
    counted_total_cents: int
    processing_fee_total_cents: int
    provisional_credit_cents: int
    final_settlement_cents: int
    settlement_delta_cents: int
    material_variance_open_count: int
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SealedBag(TypedDict):
    id: str
    deposit_ticket_id: str
    seal_number: str
    bag_type: str
    declared_amount_cents: int
    declared_note_count: int
    declared_coin_weight_grams: int
    custody_status: str
    count_status: str
    counted_amount_cents: int
    counted_note_count: int
    counted_coin_weight_grams: int
    variance_cents: int
    materiality_flag: bool
    processing_fee_cents: int
    seized_amount_cents: int
    claim_adjustment_cents: int
    settlement_amount_cents: int
    counted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CountingMachine(TypedDict):
    id: str
    vault_id: str
    machine_code: str
    machine_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CountSession(TypedDict):
    id: str
    sealed_bag_id: str
    counting_machine_id: str
    operator_user_id: str
    verifier_user_id: Optional[str]
    window_start: str
    window_end: str
    status: str
    counted_amount_cents: int
    counted_note_count: int
    counted_coin_weight_grams: int
    seized_face_value_cents: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FitnessLot(TypedDict):
    id: str
    count_session_id: str
    fed_deposit_id: Optional[str]
    category: str
    denomination_cents: int
    note_count: int
    face_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CounterfeitReport(TypedDict):
    id: str
    fitness_lot_id: str
    serial_number: str
    denomination_cents: int
    note_count: int
    status: str
    seized_face_value_cents: int
    submitted_at: Optional[str]
    case_number: Optional[str]
    correction_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiscrepancyClaim(TypedDict):
    id: str
    sealed_bag_id: str
    customer_account_id: str
    claim_type: str
    claimed_amount_cents: int
    status: str
    review_round: int
    resolution_amount_cents: int
    filed_at: str
    decided_by_user_id: Optional[str]
    info_request_note: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FedDeposit(TypedDict):
    id: str
    vault_id: str
    cash_letter_number: str
    deposit_date: str
    status: str
    declared_total_cents: int
    credited_total_cents: int
    adjustment_cents: int
    attached_lot_count: int
    submitted_at: Optional[str]
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoinOrder(TypedDict):
    id: str
    customer_account_id: str
    vault_id: str
    pickup_window_start: str
    pickup_window_end: str
    status: str
    approved_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    total_boxes_requested: int
    total_boxes_allocated: int
    fill_ratio_pct: float
    charge_cents: int
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VaultInventory(TypedDict):
    id: str
    vault_id: str
    denomination: str
    on_hand_boxes: int
    reserved_boxes: int
    available_boxes: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only records: id + created_at only ────────────────────────────

class CustodyEvent(TypedDict):
    id: str
    sealed_bag_id: str
    event_type: str
    actor_user_id: str
    location_code: str
    observed_seal_number: str
    sequence_no: int
    seal_intact: bool
    created_at: str


class CoinOrderLine(TypedDict):
    id: str
    coin_order_id: str
    denomination: str
    boxes_requested: int
    boxes_allocated: int
    boxes_returned: int
    line_face_value_cents: int
    created_at: str


# ─── Read-only projections ────────────────────────────────────────────────

class CustomerStatement(TypedDict):
    customer_account_id: str
    ledger_balance_cents: int
    provisional_credit_cents: int
    available_balance_cents: int
    risk_score: float
    risk_grade: str
    projected_risk_score: float
    projected_risk_grade: str
    open_ticket_count: int
    settled_ticket_count: int
    open_claim_count: int


class CashLetterReconciliation(TypedDict):
    vault_id: str
    shipped_total_cents: int
    credited_total_cents: int
    outstanding_cents: int
    net_adjustment_cents: int
    reconciled: bool


__all__ = [
    "UserRole",
    "VaultPosture",
    "CoinDenomination",
    "CustomerTier",
    "CustomerAccountStatus",
    "RiskGrade",
    "DepositTicketStatus",
    "BagType",
    "CustodyStatus",
    "CountStatus",
    "CustodyEventType",
    "MachineType",
    "MachineStatus",
    "CountSessionStatus",
    "FitnessLotCategory",
    "FitnessLotStatus",
    "CounterfeitReportStatus",
    "ClaimType",
    "DiscrepancyClaimStatus",
    "FedDepositStatus",
    "CoinOrderStatus",
    "Vault",
    "CustomerAccount",
    "DepositTicket",
    "SealedBag",
    "CountingMachine",
    "CountSession",
    "FitnessLot",
    "CounterfeitReport",
    "DiscrepancyClaim",
    "FedDeposit",
    "CoinOrder",
    "VaultInventory",
    "CustodyEvent",
    "CoinOrderLine",
    "CustomerStatement",
    "CashLetterReconciliation",
]
