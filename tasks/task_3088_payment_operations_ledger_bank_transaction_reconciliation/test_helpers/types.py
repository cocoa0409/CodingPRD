"""Domain types: entity TypedDicts, status enums, role enum.

Field names are PRD-exact. Note that ``AuditEvent`` is declared with
``common_fields: false`` in the contract: it carries an ``id`` and a
``created_at`` and nothing else from the standard quartet, so its TypedDict
deliberately omits ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LEDGER_CONTROLLER = "LedgerController"
    PAYMENT_INITIATOR = "PaymentInitiator"
    PAYMENT_APPROVER = "PaymentApprover"
    PAYMENT_OPS_ANALYST = "PaymentOpsAnalyst"
    PAYMENT_OPS_APPROVER = "PaymentOpsApprover"
    COUNTERPARTY_USER = "CounterpartyUser"
    AUDITOR = "Auditor"


# ─── Status enums ─────────────────────────────────────

class LedgerStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LegalEntityType(str, Enum):
    PLATFORM = "PLATFORM"
    ORGANISATION = "ORGANISATION"


class CounterpartyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


class RelationshipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RelationshipPurpose(str, Enum):
    ACCOUNT_SHARING = "ACCOUNT_SHARING"
    PAYMENT_RAIL_AGREEMENT = "PAYMENT_RAIL_AGREEMENT"
    DISPUTE_CHANNEL = "DISPUTE_CHANNEL"


class BankAccountStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class VirtualAccountStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class StatementStatus(str, Enum):
    IMPORTED = "IMPORTED"
    RECONCILING = "RECONCILING"
    RECONCILED = "RECONCILED"
    DISCREPANCY = "DISCREPANCY"
    REVISED = "REVISED"
    SUPERSEDED = "SUPERSEDED"


class LineMatchState(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    IGNORED = "IGNORED"


class PaymentOrderStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ACH_DISPATCHED = "ACH_DISPATCHED"
    WIRE_DISPATCHED = "WIRE_DISPATCHED"
    RTP_DISPATCHED = "RTP_DISPATCHED"
    CHECK_DISPATCHED = "CHECK_DISPATCHED"
    IN_FLIGHT = "IN_FLIGHT"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class PaymentOrderSettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    IN_SETTLEMENT = "IN_SETTLEMENT"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class TransactionLifecycleStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    VOID = "VOID"
    REJECTED = "REJECTED"


class TransactionSettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    IN_SETTLEMENT = "IN_SETTLEMENT"
    SETTLED = "SETTLED"


class TransactionEntryType(str, Enum):
    ORIGINATING = "ORIGINATING"
    RETURN = "RETURN"
    REVERSAL = "REVERSAL"
    FEE = "FEE"
    ADJUSTMENT = "ADJUSTMENT"
    DEPOSIT = "DEPOSIT"


class Direction(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class Rail(str, Enum):
    ACH = "ACH"
    WIRE = "WIRE"
    RTP = "RTP"
    CHECK = "CHECK"


class SettlementSpeed(str, Enum):
    STANDARD = "STANDARD"
    SAME_DAY = "SAME_DAY"


class ExceptionKind(str, Enum):
    UNMATCHED_DEPOSIT = "UNMATCHED_DEPOSIT"
    RETURN = "RETURN"
    REVERSAL = "REVERSAL"
    FAILED_PAYMENT = "FAILED_PAYMENT"
    STATEMENT_VARIANCE = "STATEMENT_VARIANCE"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    AGING = "AGING"
    ESCALATED = "ESCALATED"
    CRITICAL = "CRITICAL"


class ReleaseRequestState(str, Enum):
    PENDING = "PENDING"
    SATISFIED = "SATISFIED"
    DECLINED = "DECLINED"
    DENIED = "DENIED"


class SettlementPoolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ForcedSettlementStatus(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class MatchingAlgorithm(str, Enum):
    POSTED_NET = "POSTED_NET"
    SETTLED_SINGLE = "SETTLED_SINGLE"


# ─── Entity TypedDicts (common_fields: true) ──────────

class Ledger(TypedDict):
    id: str
    name: str
    currency: str
    period_index: int
    period_opened_utc: str
    period_closed_through_index: int
    pending_balance_cents: int
    posted_balance_cents: int
    delivered_fee_transfers_cents: int
    undeliverable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LegalEntity(TypedDict):
    id: str
    legal_name: str
    short_code: str
    entity_type: str
    home_ledger_id: Optional[str]
    default_velocity_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class Counterparty(TypedDict):
    id: str
    legal_entity_id: str
    display_name: str
    external_ref: str
    velocity_limit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CounterpartyRelationship(TypedDict):
    id: str
    legal_entity_id: str
    partner_legal_entity_id: str
    purpose: str
    account_data_sharing: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BankAccount(TypedDict):
    id: str
    legal_entity_id: str
    institution_name: str
    routing_number: str
    account_number_last4: str
    supported_rails: List[str]
    available_funds_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VirtualAccount(TypedDict):
    id: str
    bank_account_id: str
    virtual_account_number: str
    reference_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BankStatement(TypedDict):
    id: str
    bank_account_id: str
    institution_ref: str
    cycle_date: str
    opening_balance_cents: int
    closing_balance_cents: int
    matching_algorithm: str
    revision_number: int
    supersedes_statement_id: Optional[str]
    matched_posted_cents: int
    unmatched_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StatementLine(TypedDict):
    id: str
    bank_statement_id: str
    bank_reference: str
    amount_cents: int
    direction: str
    effective_at: str
    embedded_reference_code: Optional[str]
    match_state: str
    created_at: str
    updated_at: str
    version: int


class PaymentOrder(TypedDict):
    id: str
    legal_entity_id: str
    ledger_id: str
    counterparty_id: str
    source_account_id: str
    rail: str
    direction: str
    amount_cents: int
    settlement_speed: str
    idempotency_key: str
    requested_release_utc: Optional[str]
    payable_to_name: Optional[str]
    cutoffs: List[dict]
    cutoff_snapshot_utc: Optional[str]
    status: str
    settlement_status: str
    initiator_user_id: str
    approver_user_id: Optional[str]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    ledger_id: str
    payment_order_id: Optional[str]
    entry_type: str
    direction: str
    amount_cents: int
    net_effect_cents: int
    value_effective_utc: str
    reverses_transaction_id: Optional[str]
    refunds_transaction_id: Optional[str]
    lifecycle_status: str
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class ExceptionItem(TypedDict):
    id: str
    ledger_id: str
    payment_order_id: Optional[str]
    bank_statement_id: Optional[str]
    kind: str
    amount_cents: int
    attributed_fee_cents: int
    attributable_amount_cents: int
    opened_utc: str
    closing_period_utc: Optional[str]
    age_business_days: int
    aging_bucket: str
    status: str
    assignee_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementPool(TypedDict):
    id: str
    ledger_id: str
    name: str
    member_bank_account_ids: List[str]
    forced_settlement_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PoolMembership(TypedDict):
    id: str
    settlement_pool_id: str
    bank_account_id: str
    weight_units: int
    created_at: str
    updated_at: str
    version: int


class ReleaseRequest(TypedDict):
    id: str
    payment_order_id: str
    counterparty_id: str
    initiator_user_id: str
    needed_by_utc: str
    reason: str
    request_state: str
    created_at: str
    updated_at: str
    version: int


class BankingCalendar(TypedDict):
    id: str
    legal_entity_id: str
    calendar_date: str
    timezone: str
    is_open: bool
    cutoffs: List[dict]
    allowed_rails: List[str]
    created_at: str
    updated_at: str
    version: int


# ─── AuditEvent (common_fields: false) ────────────────
# Append-only: carries id and created_at ONLY. Never mint updated_at or version.

class AuditEvent(TypedDict):
    id: str
    ledger_id: str
    actor_user_id: str
    actor_role: str
    action: str
    target_entity_type: str
    target_entity_id: str
    sequence_number: int
    details: dict
    created_at: str