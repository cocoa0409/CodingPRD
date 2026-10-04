"""Domain types: entity shapes, status enums, and the role enum.

These declarations mirror the resource model described in the PRD: each
primary resource carries ``id``, ``created_at``, ``updated_at`` and
``version``; the four append-only records (DepositReturn, RepaymentAllocation,
AbuseEvent, LedgerEntry) carry ``id`` and ``created_at`` only.
"""

from enum import Enum
from typing import Optional, TypedDict


class MemberStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ELIGIBLE = "ELIGIBLE"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AccountType(str, Enum):
    SPENDING = "SPENDING"
    SAVINGS = "SAVINGS"


class OriginatorType(str, Enum):
    PAYROLL = "PAYROLL"
    OTHER = "OTHER"


class DepositStatus(str, Enum):
    RECEIVED_FILE = "RECEIVED_FILE"
    POSTED_EARLY = "POSTED_EARLY"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"


class EarlyPostingStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    REVERSED = "REVERSED"


class ReturnCode(str, Enum):
    R01_INSUFFICIENT = "R01_INSUFFICIENT"
    R02_CLOSED = "R02_CLOSED"
    R03_NO_ACCOUNT = "R03_NO_ACCOUNT"
    R07_REVOKED = "R07_REVOKED"
    R08_STOPPED = "R08_STOPPED"


class AdvanceOrigin(str, Enum):
    MEMBER_INITIATED = "MEMBER_INITIATED"
    RECLAIM_SHORTFALL = "RECLAIM_SHORTFALL"


class AdvanceStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_REPAID = "PARTIALLY_REPAID"
    REPAID = "REPAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class AllocationMode(str, Enum):
    WATERFALL = "WATERFALL"
    PRO_RATA = "PRO_RATA"


class EvaluationMode(str, Enum):
    BATCH = "BATCH"
    REALTIME = "REALTIME"


class ProfileStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class AdjustmentDirection(str, Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    FLAT = "FLAT"


class AdjustmentStatus(str, Enum):
    PENDING_NOTICE = "PENDING_NOTICE"
    NOTIFIED = "NOTIFIED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class AbuseEventType(str, Enum):
    DEPOSIT_REROUTE = "DEPOSIT_REROUTE"
    CUSHION_CYCLING = "CUSHION_CYCLING"
    FIRST_PARTY_FRAUD = "FIRST_PARTY_FRAUD"


class LedgerEntryType(str, Enum):
    ADVANCE_CREDIT = "ADVANCE_CREDIT"
    ADVANCE_REPAYMENT_DEBIT = "ADVANCE_REPAYMENT_DEBIT"
    EARLY_POSTING_CREDIT = "EARLY_POSTING_CREDIT"
    EARLY_POSTING_REVERSAL = "EARLY_POSTING_REVERSAL"
    DEPOSIT_SETTLEMENT = "DEPOSIT_SETTLEMENT"
    DEPOSIT_RETURN_DEBIT = "DEPOSIT_RETURN_DEBIT"
    PROVISIONAL_CREDIT = "PROVISIONAL_CREDIT"
    PROVISIONAL_REVERSAL = "PROVISIONAL_REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class LedgerEntryStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class RunStatus(str, Enum):
    OPEN = "OPEN"
    BALANCED = "BALANCED"
    DISCREPANCY = "DISCREPANCY"
    RESOLVED = "RESOLVED"


class DisputeType(str, Enum):
    EARLY_POSTING_REVERSAL = "EARLY_POSTING_REVERSAL"
    DEPOSIT_RETURN_CLAIM = "DEPOSIT_RETURN_CLAIM"


class CaseStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_MEMBER = "RESOLVED_MEMBER"
    RESOLVED_BANK = "RESOLVED_BANK"


class ProvisionalStatus(str, Enum):
    NONE = "NONE"
    PROVISIONAL_ISSUED = "PROVISIONAL_ISSUED"
    PROVISIONAL_MADE_FINAL = "PROVISIONAL_MADE_FINAL"
    PROVISIONAL_RECLAIMED = "PROVISIONAL_RECLAIMED"


class UserRole(str, Enum):
    MEMBER = "Member"
    PROGRAM_OPS = "ProgramOps"
    SPONSOR_BANK_OPS = "SponsorBankOps"
    DISPUTES_AGENT = "DisputesAgent"


class Member(TypedDict, total=False):
    id: str
    external_ref: str
    full_name: str
    enrolled_at: str
    status: str
    tenure_days: int
    current_limit_cents: int
    consecutive_on_time_repayments: int
    restricted_consecutive_repayments: int
    abuse_event_count: int
    abuse_events_90d: int
    deposit_reroute_flag: bool
    created_at: str
    updated_at: str
    version: int


class DepositAccount(TypedDict, total=False):
    id: str
    member_id: str
    account_type: str
    currency: str
    sponsor_bank_code: str
    posted_balance_cents: int
    provisional_early_cents: int
    holds_cents: int
    outstanding_cushion_cents: int
    usable_cushion_cents: int
    available_optimistic_cents: int
    available_conservative_cents: int
    created_at: str
    updated_at: str
    version: int


class DirectDeposit(TypedDict, total=False):
    id: str
    account_id: str
    originator_id: str
    originator_type: str
    amount_cents: int
    settlement_date: str
    trace_id: str
    status: str
    qualifying: bool
    repaid_cents: int
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EarlyPosting(TypedDict, total=False):
    id: str
    deposit_id: str
    posted_amount_cents: int
    reversal_window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DepositReturn(TypedDict, total=False):
    # Append-only record: id + created_at only, no updated_at / version.
    id: str
    deposit_id: str
    return_code: str
    amount_cents: int
    shortfall_cents: int
    created_at: str


class OverdraftAdvance(TypedDict, total=False):
    id: str
    account_id: str
    origin: str
    principal_cents: int
    outstanding_cents: int
    status: str
    repaid_at: Optional[str]
    on_time: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class RepaymentAllocation(TypedDict, total=False):
    # Append-only record: id + created_at only, no updated_at / version.
    id: str
    advance_id: str
    deposit_id: str
    amount_cents: int
    allocation_mode: str
    created_at: str


class EligibilityProfile(TypedDict, total=False):
    id: str
    member_id: str
    evaluation_mode: str
    score: int
    regularity_points: int
    tenure_points: int
    repayment_points: int
    abuse_penalty: int
    computed_limit_cents: int
    delta_vs_current_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CushionLimitAdjustment(TypedDict, total=False):
    id: str
    member_id: str
    old_limit_cents: int
    new_limit_cents: int
    direction: str
    status: str
    effective_at: str
    notified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbuseEvent(TypedDict, total=False):
    # Append-only record: id + created_at only, no updated_at / version.
    id: str
    member_id: str
    event_type: str
    evidence_note: Optional[str]
    created_at: str


class LedgerEntry(TypedDict, total=False):
    # Append-only record: id + created_at only, no updated_at / version.
    id: str
    account_id: str
    reconciliation_run_id: Optional[str]
    entry_type: str
    program_leg_cents: int
    bank_leg_cents: int
    status: str
    posted_at: str
    created_at: str


class ReconciliationRun(TypedDict, total=False):
    id: str
    sponsor_bank_code: str
    period_start: str
    period_end: str
    bank_reported_net_cents: int
    program_net_cents: int
    bank_net_cents: int
    discrepancy_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    member_id: str
    deposit_id: str
    dispute_type: str
    amount_cents: int
    statement: str
    case_status: str
    provisional_status: str
    provisional_due_at: str
    resolution_due_at: str
    provisional_overdue: bool
    created_at: str
    updated_at: str
    version: int
