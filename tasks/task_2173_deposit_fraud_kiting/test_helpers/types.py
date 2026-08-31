"""Domain types for the Deposit Fraud & Kiting Detection API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    OPERATIONS_ADMIN = "OperationsAdmin"
    FRAUD_ANALYST = "FraudAnalyst"
    FRAUD_SUPERVISOR = "FraudSupervisor"
    BSA_OFFICER = "BsaOfficer"
    LEGAL_COUNSEL = "LegalCounsel"
    ACCOUNT_HOLDER = "AccountHolder"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class KycTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ProductType(str, Enum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    MONEY_MARKET = "MONEY_MARKET"


class OpenChannel(str, Enum):
    BRANCH = "BRANCH"
    ONLINE = "ONLINE"
    MOBILE = "MOBILE"


class LifecycleStatus(str, Enum):
    PENDING_FUNDING = "PENDING_FUNDING"
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"
    CHARGED_OFF = "CHARGED_OFF"


class AccessPosture(str, Enum):
    NORMAL = "NORMAL"
    STEP_UP_REQUIRED = "STEP_UP_REQUIRED"
    LOCKED = "LOCKED"


class RiskBand(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class RiskScoreBasis(str, Enum):
    PROVISIONAL_AT_OPEN = "PROVISIONAL_AT_OPEN"
    REFRESHED = "REFRESHED"


class AtoIndicatorCode(str, Enum):
    NEW_DEVICE = "NEW_DEVICE"
    GEO_VELOCITY = "GEO_VELOCITY"
    CREDENTIAL_STUFFING = "CREDENTIAL_STUFFING"
    PROFILE_CHANGE = "PROFILE_CHANGE"
    DORMANT_REACTIVATION = "DORMANT_REACTIVATION"
    PAYEE_ADDED = "PAYEE_ADDED"


class ClosureReason(str, Enum):
    MULE_SUBSTANTIATED = "MULE_SUBSTANTIATED"
    KITING_SUBSTANTIATED = "KITING_SUBSTANTIATED"


class SourceType(str, Enum):
    EXTERNAL_ACH = "EXTERNAL_ACH"
    WIRE = "WIRE"
    CARD_PUSH = "CARD_PUSH"


class VerificationStatus(str, Enum):
    DECLARED = "DECLARED"
    MICRO_DEPOSIT_SENT = "MICRO_DEPOSIT_SENT"
    FAILED_ATTEMPT = "FAILED_ATTEMPT"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"


class LinkType(str, Enum):
    SHARED_DEVICE = "SHARED_DEVICE"
    SHARED_ADDRESS = "SHARED_ADDRESS"
    SHARED_PHONE = "SHARED_PHONE"
    TRANSFER_COUNTERPARTY = "TRANSFER_COUNTERPARTY"


class ItemType(str, Enum):
    CHECK = "CHECK"
    ACH = "ACH"
    CASH = "CASH"


class DepositItemStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    RETURNED = "RETURNED"


class ReturnReason(str, Enum):
    NSF = "NSF"
    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"
    UNCOLLECTED_FUNDS = "UNCOLLECTED_FUNDS"
    STOP_PAYMENT = "STOP_PAYMENT"


class HoldType(str, Enum):
    STANDARD = "STANDARD"
    EXCEPTION_NEW_ACCOUNT = "EXCEPTION_NEW_ACCOUNT"
    EXCEPTION_LARGE_DEPOSIT = "EXCEPTION_LARGE_DEPOSIT"
    EXCEPTION_RISK = "EXCEPTION_RISK"
    EXCEPTION_FRAUD = "EXCEPTION_FRAUD"


class CheckHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    OVERRIDDEN = "OVERRIDDEN"
    CHARGED_BACK = "CHARGED_BACK"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    RETURN_FOR_INFO = "RETURN_FOR_INFO"


class CaseType(str, Enum):
    KITING = "KITING"
    MULE = "MULE"


class CaseStatus(str, Enum):
    OPENED = "OPENED"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    CLOSED = "CLOSED"


class DetectionSource(str, Enum):
    KITING_SCAN = "KITING_SCAN"
    ANALYST_MANUAL = "ANALYST_MANUAL"


class ScanMode(str, Enum):
    STRICT = "STRICT"
    INCLUSIVE = "INCLUSIVE"


class CaseDecision(str, Enum):
    SUBSTANTIATE = "SUBSTANTIATE"
    UNSUBSTANTIATE = "UNSUBSTANTIATE"
    REOPEN = "REOPEN"


class ChargeOffStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    BOOKED = "BOOKED"
    REFERRED_TO_RECOVERY = "REFERRED_TO_RECOVERY"
    RECOVERED_PARTIAL = "RECOVERED_PARTIAL"
    RECOVERED_FULL = "RECOVERED_FULL"
    REVERSED = "REVERSED"
    SUPERSEDED = "SUPERSEDED"


class SubpoenaStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_LEGAL_REVIEW = "UNDER_LEGAL_REVIEW"
    PRODUCED = "PRODUCED"
    OBJECTED = "OBJECTED"
    QUASHED = "QUASHED"


class SubpoenaDisposition(str, Enum):
    PRODUCE = "PRODUCE"
    OBJECT = "OBJECT"
    QUASH = "QUASH"


class ReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class SuspectedActivityCode(str, Enum):
    KITING = "KITING"
    MULE_ACTIVITY = "MULE_ACTIVITY"
    STRUCTURING = "STRUCTURING"
    ACCOUNT_TAKEOVER = "ACCOUNT_TAKEOVER"


class ReferralDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class SettlementOutcome(str, Enum):
    CLEARED = "CLEARED"
    RETURNED = "RETURNED"


# ---------------------------------------------------------------------------
# Entity shapes.  PRD §2.4: all eleven resource kinds expose id, created_at,
# updated_at and version.
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    legal_name: str
    tin_last4: str
    kyc_tier: str
    watchlist_hit: bool
    preservation_hold_active: bool
    open_fraud_case_count: int
    created_at: str
    updated_at: str
    version: int


class DepositAccount(TypedDict):
    id: str
    customer_id: str
    product_type: str
    open_channel: str
    opened_at: str
    lifecycle_status: str
    access_posture: str
    risk_score: int
    risk_score_basis: str
    risk_band: str
    ato_indicator_codes: List[str]
    ato_score: int
    step_up_failure_count: int
    ledger_balance_cents: int
    available_balance_cents: int
    held_amount_cents: int
    charged_off_amount_cents: int
    closure_scheduled_at: Optional[str]
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict):
    id: str
    account_id: str
    source_type: str
    routing_last4: str
    micro_deposit_cents: int
    verification_status: str
    attempt_count: int
    total_attempt_count: int
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccountLink(TypedDict):
    id: str
    from_account_id: str
    to_account_id: str
    link_type: str
    confidence_bps: int
    is_risk_bearing: bool
    created_at: str
    updated_at: str
    version: int


class DepositItem(TypedDict):
    id: str
    account_id: str
    drawee_account_id: Optional[str]
    item_type: str
    amount_cents: int
    deposit_at: str
    status: str
    settled_at: Optional[str]
    return_reason: Optional[str]
    immediate_credit_cents: int
    held_cents: int
    created_at: str
    updated_at: str
    version: int


class CheckHold(TypedDict):
    id: str
    deposit_item_id: str
    hold_type: str
    held_amount_cents: int
    hold_start_at: str
    hold_release_at: str
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HoldOverrideReview(TypedDict):
    id: str
    check_hold_id: str
    requested_release_cents: int
    release_effective_at: str
    release_window_end_at: str
    justification: str
    prepared_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    loss_exposure_cents: int
    adjusted_exposure_cents: int
    decision_note: Optional[str]
    revision_count: int
    submitted_at: Optional[str]
    decided_at: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudCase(TypedDict):
    id: str
    primary_account_id: str
    case_type: str
    status: str
    detection_source: str
    kiting_score: Optional[int]
    scan_mode: Optional[str]
    cycle_account_ids: List[str]
    exposure_at_risk_cents: int
    disposition_note: Optional[str]
    reopen_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChargeOff(TypedDict):
    id: str
    account_id: str
    gross_loss_cents: int
    collateral_offset_cents: int
    base_net_cents: int
    recovery_fee_cents: int
    net_charge_off_cents: int
    principal_recovered_cents: int
    fee_recovered_cents: int
    outstanding_loss_cents: int
    status: str
    approved_by_user_id: Optional[str]
    booked_by_user_id: Optional[str]
    ledger_balance_before_book_cents: Optional[int]
    booked_at: Optional[str]
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubpoenaRequest(TypedDict):
    id: str
    customer_id: str
    issuing_agency: str
    docket_number: str
    received_at: str
    response_due_at: str
    preservation_start_at: str
    preservation_end_at: str
    status: str
    legal_reviewed_by_user_id: Optional[str]
    responded_by_user_id: Optional[str]
    is_late: bool
    production_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BsaReferral(TypedDict):
    id: str
    fraud_case_id: str
    narrative: str
    suspected_activity_code: str
    aggregate_amount_cents: int
    status: str
    drafted_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    return_reason: Optional[str]
    revision_count: int
    submitted_at: Optional[str]
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KitingScanResult(TypedDict):
    kiting_score: int
    cycle_length: int
    cycle_account_ids: List[str]
    qualifying_item_count: int
    deposited_cents: int
    uncollected_cents: int
    uncollected_ratio_bps: int
    detected: bool
    fraud_case_id: Optional[str]
