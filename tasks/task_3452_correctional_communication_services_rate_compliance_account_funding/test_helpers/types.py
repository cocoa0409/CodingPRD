"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    """The six roles recognized by the platform (PRD §2.1)."""

    PLATFORM_ADMIN = "PlatformAdmin"
    STATE_REGULATOR = "StateRegulator"
    FACILITY_STAFF = "FacilityStaff"
    ACCOUNT_HOLDER = "AccountHolder"
    RECIPIENT_PARTY = "RecipientParty"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class FacilityStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RefundMethod(str, Enum):
    """Jurisdiction-selected refund payout variant (PRD §3.8)."""

    SIMPLE_BALANCE = "SIMPLE_BALANCE"
    LIFO_NET = "LIFO_NET"


class CommissionBasis(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class RateScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class InmateStatus(str, Enum):
    IN_CUSTODY = "IN_CUSTODY"
    RELEASED = "RELEASED"


class FundingModel(str, Enum):
    PREPAID = "PREPAID"
    COLLECT = "COLLECT"
    DEBIT = "DEBIT"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class EscheatStatus(str, Enum):
    NONE = "NONE"
    DORMANT = "DORMANT"
    NOTICE_SENT = "NOTICE_SENT"
    REMITTED = "REMITTED"
    CLAIMED = "CLAIMED"


class LedgerEntryType(str, Enum):
    """FundingTransaction.type values (PRD §2.5)."""

    DEPOSIT = "DEPOSIT"
    DEPOSIT_FEE = "DEPOSIT_FEE"
    CALL_CHARGE = "CALL_CHARGE"
    MESSAGE_CHARGE = "MESSAGE_CHARGE"
    MESSAGE_REFUND = "MESSAGE_REFUND"
    VIDEO_CHARGE = "VIDEO_CHARGE"
    VIDEO_REFUND = "VIDEO_REFUND"
    CLOSURE_FEE = "CLOSURE_FEE"
    REFUND_PAYOUT = "REFUND_PAYOUT"
    ESCHEAT_REMITTANCE = "ESCHEAT_REMITTANCE"


class RelationshipType(str, Enum):
    FAMILY = "FAMILY"
    FRIEND = "FRIEND"
    ATTORNEY = "ATTORNEY"
    LEGAL_AID = "LEGAL_AID"
    OTHER = "OTHER"


class VerificationStatus(str, Enum):
    VERIFICATION_SENT = "VERIFICATION_SENT"
    VERIFIED = "VERIFIED"


class BlockStatus(str, Enum):
    NOT_BLOCKED = "NOT_BLOCKED"
    BLOCKED = "BLOCKED"


class PrivilegeStatus(str, Enum):
    NONE = "NONE"
    PRIVILEGE_REQUESTED = "PRIVILEGE_REQUESTED"
    PRIVILEGED = "PRIVILEGED"
    REVOKED = "REVOKED"


class CallType(str, Enum):
    LOCAL = "LOCAL"
    INTRASTATE = "INTRASTATE"
    INTERSTATE = "INTERSTATE"
    INTERNATIONAL = "INTERNATIONAL"


class CallStatus(str, Enum):
    CONNECTED = "CONNECTED"
    COMPLETED = "COMPLETED"
    NOT_CONNECTED = "NOT_CONNECTED"


class CutoffReason(str, Enum):
    NONE = "NONE"
    BALANCE_EXHAUSTED = "BALANCE_EXHAUSTED"
    CREDIT_LIMIT_REACHED = "CREDIT_LIMIT_REACHED"


class RecordingStatus(str, Enum):
    RECORDED = "RECORDED"
    EXEMPT_PRIVILEGED = "EXEMPT_PRIVILEGED"


class VideoSessionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class MessageStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"


class RefundSource(str, Enum):
    CLOSURE = "CLOSURE"
    ESCHEAT_CLAIM = "ESCHEAT_CLAIM"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class ComplaintCategory(str, Enum):
    RATE_DISPUTE = "RATE_DISPUTE"
    FEE_DISCLOSURE = "FEE_DISCLOSURE"
    SERVICE_QUALITY = "SERVICE_QUALITY"
    PRIVACY_CONCERN = "PRIVACY_CONCERN"
    WRONGFUL_BLOCK = "WRONGFUL_BLOCK"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    ESCALATED_TO_REGULATOR = "ESCALATED_TO_REGULATOR"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 common fields: id, created_at, updated_at,
# version — except the append-only ledger, which carries only id/created_at).
# ---------------------------------------------------------------------------


class Facility(TypedDict):
    id: str
    name: str
    state_code: str
    video_booth_count: int
    video_turnover_minutes: int
    max_session_minutes: int
    visiting_open_minutes: int
    visiting_close_minutes: int
    daily_session_limit_per_inmate: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryCap(TypedDict):
    id: str
    state_code: str
    max_per_minute_cents: int
    max_connection_fee_cents: int
    max_ancillary_fee_cents: int
    max_deposit_fee_cents: int
    max_commission_pct: float
    refund_method: str
    dormancy_days: int
    claim_window_days: int
    created_at: str
    updated_at: str
    version: int


class FacilityContract(TypedDict):
    id: str
    facility_id: str
    commission_pct: float
    commission_basis: str
    deposit_fee_cents: int
    closure_fee_cents: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict):
    id: str
    contract_id: str
    local_per_minute_cents: int
    intrastate_per_minute_cents: int
    interstate_per_minute_cents: int
    international_per_minute_cents: int
    connection_fee_cents: int
    message_price_cents: int
    video_session_fee_cents: int
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inmate(TypedDict):
    id: str
    facility_id: str
    booking_number: str
    full_name: str
    housing_unit: Optional[str]
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    facility_id: str
    inmate_id: str
    funding_model: str
    owner_name: str
    owner_contact: str
    collect_credit_limit_cents: Optional[int]
    status: str
    balance_cents: int
    closed_at: Optional[str]
    balance_at_closure_cents: Optional[int]
    refundable_computed_cents: Optional[int]
    retained_fees_cents: int
    refunded_total_cents: int
    escheated_total_cents: int
    latest_refund_request_id: Optional[str]
    unclaimed_balance_cents: int
    unclaimed_since: Optional[str]
    escheat_status: str
    escheat_notice_sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingTransaction(TypedDict):
    """Append-only ledger row: carries ONLY id + created_at as common fields
    (PRD §2.5 — no updated_at, no version)."""

    id: str
    account_id: str
    type: str
    amount_cents: int
    reference_id: Optional[str]
    note: str
    created_at: str


class RecipientNumber(TypedDict):
    id: str
    account_id: str
    e164_number: str
    label: str
    relationship_type: str
    verification_status: str
    verification_code: str
    consent_to_recording: bool
    block_status: str
    block_reason: Optional[str]
    privilege_status: str
    privilege_decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CallRecord(TypedDict):
    id: str
    account_id: str
    inmate_id: str
    facility_id: str
    recipient_number_id: str
    rate_schedule_id: str
    call_type: str
    status: str
    applied_per_minute_cents: int
    applied_connection_fee_cents: int
    connected_at: str
    ended_at: Optional[str]
    duration_seconds: Optional[int]
    billable_minutes: Optional[int]
    total_charge_cents: Optional[int]
    cutoff_reason: str
    recording_status: str
    created_at: str
    updated_at: str
    version: int


class VideoSession(TypedDict):
    id: str
    facility_id: str
    inmate_id: str
    account_id: str
    visitor_name: str
    scheduled_start: str
    scheduled_end: str
    duration_minutes: int
    status: str
    charge_cents: Optional[int]
    confirmed_at: Optional[str]
    cancelled_at: Optional[str]
    closed_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TabletMessage(TypedDict):
    id: str
    account_id: str
    inmate_id: str
    facility_id: str
    body_text: str
    price_cents: int
    status: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict):
    id: str
    account_id: str
    source: str
    status: str
    requested_amount_cents: int
    computed_payout_cents: Optional[int]
    refund_method_applied: Optional[str]
    requested_by_user_id: str
    requested_by_role: str
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    paid_by_user_id: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    facility_id: str
    subject_account_id: Optional[str]
    subject_call_id: Optional[str]
    category: str
    description: str
    status: str
    filed_by_user_id: str
    filed_by_role: str
    reviewed_by_user_id: Optional[str]
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    escalated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "FacilityStatus",
    "RefundMethod",
    "CommissionBasis",
    "ContractStatus",
    "RateScheduleStatus",
    "InmateStatus",
    "FundingModel",
    "AccountStatus",
    "EscheatStatus",
    "LedgerEntryType",
    "RelationshipType",
    "VerificationStatus",
    "BlockStatus",
    "PrivilegeStatus",
    "CallType",
    "CallStatus",
    "CutoffReason",
    "RecordingStatus",
    "VideoSessionStatus",
    "MessageStatus",
    "RefundSource",
    "RefundStatus",
    "ComplaintCategory",
    "ComplaintStatus",
    "Facility",
    "RegulatoryCap",
    "FacilityContract",
    "RateSchedule",
    "Inmate",
    "Account",
    "FundingTransaction",
    "RecipientNumber",
    "CallRecord",
    "VideoSession",
    "TabletMessage",
    "RefundRequest",
    "Complaint",
]
