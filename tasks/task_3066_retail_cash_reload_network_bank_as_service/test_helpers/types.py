"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the retail cash reload network contract described in PRD.md.
Every entity in this domain carries the full set of system-managed properties
(id, created_at, updated_at, version) — there is no append-only entity.
"""
from enum import Enum
from typing import TypedDict, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BANK_SPONSOR = "BankSponsor"
    PROGRAM_MANAGER = "ProgramManager"
    RETAILER_CLERK = "RetailerClerk"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SETTLEMENT_OPERATOR = "SettlementOperator"


class ProgramPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class BrandPartnerStatus(str, Enum):
    PENDING_ONBOARDING = "PENDING_ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class SuspensionSource(str, Enum):
    NONE = "NONE"
    POSTURE = "POSTURE"
    COMPLIANCE = "COMPLIANCE"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LocationStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    FUNDED = "FUNDED"
    DRAINED = "DRAINED"


class HoldStatus(str, Enum):
    CLEAR = "CLEAR"
    REVIEW = "REVIEW"
    FROZEN = "FROZEN"


class LoadStatus(str, Enum):
    INITIATED = "INITIATED"
    FUNDED = "FUNDED"
    DECLINED = "DECLINED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ReversalReason(str, Enum):
    NONE = "NONE"
    AML_CONFIRMED = "AML_CONFIRMED"
    DISPUTE_FAVOR_CARDHOLDER = "DISPUTE_FAVOR_CARDHOLDER"
    RETAILER_REQUEST = "RETAILER_REQUEST"
    STRUCTURING = "STRUCTURING"


class AlertType(str, Enum):
    VELOCITY = "VELOCITY"
    STRUCTURING = "STRUCTURING"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class DisputeReason(str, Enum):
    UNAUTHORIZED_LOAD = "UNAUTHORIZED_LOAD"
    INCORRECT_AMOUNT = "INCORRECT_AMOUNT"
    GOODS_NOT_RECEIVED = "GOODS_NOT_RECEIVED"
    ERROR_RESOLUTION = "ERROR_RESOLUTION"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    RETAILER_RESPONSE = "RETAILER_RESPONSE"
    PROGRAM_REVIEW = "PROGRAM_REVIEW"
    RESOLVED_CARDHOLDER = "RESOLVED_CARDHOLDER"
    RESOLVED_RETAILER = "RESOLVED_RETAILER"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class AllocationStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    RECOVERED = "RECOVERED"


class BatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    CLAWED_BACK = "CLAWED_BACK"


class FloatWindowStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CardholderAgreementType(str, Enum):
    REG_E = "REG_E"
    VOLUNTARY = "VOLUNTARY"
    CORPORATE = "CORPORATE"


# common_fields: true — carries id + created_at + updated_at + version
class BankSponsor(TypedDict):
    id: str
    legal_name: str
    charter_state_code: str
    sponsorship_capacity_programs: int
    oversight_tier: str
    regulator_exam_due_at: str
    active_program_count: int
    oversight_reviews_completed: int
    is_capacity_exhausted: bool
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    name: str
    sponsor_bank_id: str
    program_type: str
    settlement_cycle: str
    oversight_review_due_at: str
    compliance_posture: str
    open_aml_alert_count: int
    posture_breach_count: int
    posture_score: float
    is_oversight_overdue: bool
    last_posture_review_at: str
    suspended_brand_count: int
    allocated_loss_total_cents: int
    unallocated_confirmed_loss_cents: int
    created_at: str
    updated_at: str
    version: int


class BrandPartner(TypedDict):
    id: str
    program_id: str
    brand_name: str
    services_scope: List[str]
    card_issuance_enabled: bool
    ledgering_enabled: bool
    compliance_oversight_enabled: bool
    partner_status: str
    suspension_source: str
    onboarding_checklist_complete: bool
    open_dispute_count: int
    created_at: str
    updated_at: str
    version: int


class RetailerAgreement(TypedDict):
    id: str
    program_id: str
    retailer_name: str
    fee_split_retailer_pct: float
    fee_split_program_pct: float
    per_transaction_limit_cents: int
    daily_location_limit_cents: int
    settlement_period_hours: int
    reload_enabled: bool
    agreement_status: str
    float_position_cents: int
    settled_fee_total_cents: int
    accrual_pending_cents: int
    contract_version_locked: bool
    created_at: str
    updated_at: str
    version: int


class ReloadLocation(TypedDict):
    id: str
    retailer_agreement_id: str
    location_code: str
    state_code: str
    register_count: int
    location_status: str
    daily_accepted_cents: int
    daily_txn_count: int
    aml_velocity_score: float
    is_velocity_breached: bool
    last_epoch_index: int
    effective_per_transaction_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class CardAccount(TypedDict):
    id: str
    program_id: str
    brand_partner_id: str
    account_ref: str
    cardholder_name: str
    cardholder_agreement_type: str
    balance_cents: int
    ledger_posted_cents: int
    ledger_reversed_cents: int
    funding_status: str
    compliance_hold_status: str
    window_load_count: int
    window_load_cents: int
    structuring_txn_count: int
    is_structuring: bool
    frozen_at: str
    created_at: str
    updated_at: str
    version: int


class LoadTransaction(TypedDict):
    id: str
    reload_location_id: str
    card_account_id: str
    settlement_batch_id: str
    principal_cents: int
    convenience_fee_cents: float
    posted_total_cents: float
    retailer_fee_share_cents: float
    program_fee_share_cents: float
    load_status: str
    reversal_reason: str
    risk_flag: str
    funded_at: str
    reversed_at: str
    epoch_index: int
    created_at: str
    updated_at: str
    version: int


class AmlAlert(TypedDict):
    id: str
    program_id: str
    card_account_id: str
    alert_type: str
    window_start_at: str
    window_end_at: str
    observed_txn_count: int
    observed_total_cents: int
    structuring_hit_count: int
    severity: str
    alert_status: str
    raised_by_analyst_id: str
    assigned_analyst_id: str
    confirmed_by_analyst_id: str
    linked_load_ids: List[str]
    resolution_note: str
    created_at: str
    updated_at: str
    version: int


class DisputeCase(TypedDict):
    id: str
    program_id: str
    load_transaction_id: str
    card_account_id: str
    cardholder_agreement_type: str
    dispute_reason: str
    claimed_amount_cents: int
    case_status: str
    response_round: int
    provisional_credit_cents: int
    final_liability_cents: int
    retailer_response_due_at: str
    error_resolution_eligible: bool
    retailer_position: str
    resolution: str
    created_at: str
    updated_at: str
    version: int


class LossAllocation(TypedDict):
    id: str
    program_id: str
    load_transaction_id: str
    retailer_agreement_id: str
    dispute_case_id: str
    total_loss_cents: int
    allocation_basis: str
    retailer_share_cents: int
    program_share_cents: int
    bank_share_cents: int
    allocation_status: str
    posted_at: str
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict):
    id: str
    retailer_agreement_id: str
    period_start_at: str
    period_end_at: str
    batch_status: str
    gross_principal_cents: int
    accrued_retailer_share_cents: float
    net_fee_payable_cents: float
    settlement_rounding_delta_cents: float
    chargeback_total_cents: int
    float_retained_cents: int
    settled_at: str
    created_at: str
    updated_at: str
    version: int


class FloatWindow(TypedDict):
    id: str
    reload_location_id: str
    window_start_at: str
    window_end_at: str
    armored_carrier: str
    float_amount_cents: int
    buffer_minutes: int
    window_status: str
    created_at: str
    updated_at: str
    version: int