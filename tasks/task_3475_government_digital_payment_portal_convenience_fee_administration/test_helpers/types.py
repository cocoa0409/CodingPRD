"""Domain types: entity TypedDicts, status enums, role enum.

Field sets mirror the PRD's resource model. Resources described in PRD section
2.5 as carrying only ``id`` and ``created_at`` (ContractPricingTier,
ComplianceAttestation, FeeQuote, SelfFundingLedgerEntry) deliberately omit
``updated_at`` and ``version`` here; every other resource carries the full
common field set.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    AGENCY_ADMIN = "AgencyAdmin"
    TREASURY_OFFICER = "TreasuryOfficer"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    PAYER = "Payer"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Enumerations used across entities
# ---------------------------------------------------------------------------

class AgencyType(str, Enum):
    STATE = "STATE"
    LOCAL = "LOCAL"


class FeeModel(str, Enum):
    CONVENIENCE_FEE = "CONVENIENCE_FEE"
    ABSORBED = "ABSORBED"


class AgencyStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class AccountStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    RETIRED = "RETIRED"


class AttestationType(str, Enum):
    PCI_DSS_AOC = "PCI_DSS_AOC"
    PENETRATION_TEST = "PENETRATION_TEST"
    INTEGRATION_REVIEW = "INTEGRATION_REVIEW"


class AttestationStatus(str, Enum):
    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"


class ServiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class AuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ECHECK = "ECHECK"
    WALLET = "WALLET"


class CardBrand(str, Enum):
    VISA = "VISA"
    MASTERCARD = "MASTERCARD"
    AMEX = "AMEX"
    DISCOVER = "DISCOVER"


class CardCostBucket(str, Enum):
    CONSUMER_DEBIT = "CONSUMER_DEBIT"
    CONSUMER_CREDIT = "CONSUMER_CREDIT"
    COMMERCIAL = "COMMERCIAL"


class InstrumentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    DEACTIVATED = "DEACTIVATED"


class QuoteStatus(str, Enum):
    OPEN = "OPEN"
    CONSUMED = "CONSUMED"
    VOIDED = "VOIDED"


class FundsStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"
    RETURNED = "RETURNED"
    RE_PRESENTED = "RE_PRESENTED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    EXCEPTION = "EXCEPTION"
    RECONCILED = "RECONCILED"


class ExceptionType(str, Enum):
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    DEPOSIT_LATE = "DEPOSIT_LATE"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RefundDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class ChargebackReasonCode(str, Enum):
    FRAUD = "FRAUD"
    DUPLICATE = "DUPLICATE"
    SERVICE_NOT_RECEIVED = "SERVICE_NOT_RECEIVED"
    CREDIT_NOT_ISSUED = "CREDIT_NOT_ISSUED"


class ChargebackStatus(str, Enum):
    OPENED = "OPENED"
    CONTESTED = "CONTESTED"
    ACCEPTED = "ACCEPTED"
    WON = "WON"
    LOST = "LOST"


class VerificationOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class ChargebackOutcome(str, Enum):
    WON = "WON"
    LOST = "LOST"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Agency(TypedDict):
    id: str
    legal_name: str
    agency_type: str
    default_fee_model: str
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgencySettlementAccount(TypedDict):
    id: str
    agency_id: str
    routing_number: str
    account_number_last4: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    verification_attempts: int
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractPricingTier(TypedDict):
    # PRD section 2.5: carries only id + created_at (no updated_at, no version).
    id: str
    agency_id: str
    volume_min_cents: int
    volume_max_cents: Optional[int]
    rate_bp: int
    per_txn_cents: int
    effective_month: str
    created_at: str


class ComplianceAttestation(TypedDict):
    # PRD section 2.5: carries only id + created_at (no updated_at, no version).
    id: str
    agency_id: str
    attestation_type: str
    issued_at: str
    expires_at: str
    status: str  # computed on read: CURRENT | EXPIRED
    created_at: str


class ServiceCatalogItem(TypedDict):
    id: str
    agency_id: str
    service_code: str
    name: str
    fee_model: str
    allowed_methods: List[str]
    min_amount_cents: int
    max_amount_cents: int
    gl_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StatutoryAuthorization(TypedDict):
    id: str
    service_id: str
    statute_citation: str
    disclosure_text_version: str
    fee_cap_cents: int
    effective_from: str
    effective_to: str
    status: str
    in_effect: bool  # computed on read
    created_at: str
    updated_at: str
    version: int


class Payer(TypedDict):
    id: str
    full_name: str
    email: str
    billing_zip: str
    created_at: str
    updated_at: str
    version: int


class PaymentInstrument(TypedDict):
    id: str
    payer_id: str
    method: str
    card_brand: Optional[str]
    card_cost_bucket: Optional[str]
    last4: str
    token_ref: str
    status: str
    ach_verify_failures: int
    created_at: str
    updated_at: str
    version: int


class FeeQuote(TypedDict):
    # PRD section 2.5: carries only id + created_at (no updated_at, no version).
    id: str
    service_id: str
    payer_id: str
    statutory_authorization_id: Optional[str]
    amount_cents: int
    method: str
    quoted_fee_cents: int
    payer_total_cents: int
    disclosure_text_version: Optional[str]
    service_version_pinned: int
    expires_at: str
    status: str
    created_at: str


class PaymentTransaction(TypedDict):
    id: str
    quote_id: str
    instrument_id: str
    service_id: str
    agency_id: str
    payer_id: str
    current_batch_id: Optional[str]
    method: str
    fee_model: str
    amount_cents: int
    charged_fee_cents: int
    final_fee_cents: int
    payer_total_cents: int
    funds_status: str
    representment_count: int
    captured_at: Optional[str]
    value_date: Optional[str]
    returned_at: Optional[str]
    refunded_cents: int
    charged_back_cents: int
    remaining_refundable_cents: int
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict):
    id: str
    agency_id: str
    business_date: str
    status: str
    member_count: int
    gross_amount_cents: int
    fees_withheld_cents: int
    refund_debits_cents: int
    return_debits_cents: int
    chargeback_debits_cents: int
    deposit_cents: int
    deposit_due_date: Optional[str]
    submitted_at: Optional[str]
    confirmed_at: Optional[str]
    actual_deposit_cents: Optional[int]
    open_exception_count: int
    created_at: str
    updated_at: str
    version: int


class ReconciliationException(TypedDict):
    id: str
    batch_id: str
    exception_type: str
    expected_cents: int
    actual_cents: Optional[int]
    detail: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    transaction_id: str
    amount_cents: int
    reason: str
    initiated_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargebackCase(TypedDict):
    id: str
    transaction_id: str
    reason_code: str
    network_debit_cents: Optional[int]
    opened_at: str
    evidence_due_at: str
    evidence_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SelfFundingLedgerEntry(TypedDict):
    # PRD section 2.5: carries only id + created_at (no updated_at, no version).
    id: str
    period: str
    fees_collected_cents: int
    absorbed_billed_cents: int
    absorbed_billed_flat_cents: int
    processing_costs_cents: int
    accrual_portal_recovery_cents: int
    cash_portal_recovery_cents: int
    surplus_remitted_cents: int
    pool_balance_after_cents: int
    portal_cost_remaining_accrual_cents: int
    portal_cost_remaining_cash_cents: int
    created_at: str
