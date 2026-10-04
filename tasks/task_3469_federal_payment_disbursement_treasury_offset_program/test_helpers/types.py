"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3).

Every resource carries the PRD §2.5 common fields: id, created_at, updated_at,
version. Fields marked Optional are null until a later lifecycle stage fixes them
(e.g. Offset.fee_cents stays null until the offset is APPLIED, per PRD §3.4).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --- Enums ---------------------------------------------------------------------

class UserRole(str, Enum):
    TREASURY_SUPERVISOR = "TreasurySupervisor"
    TREASURY_OPERATOR = "TreasuryOperator"
    PAYMENT_AGENCY_ANALYST = "PaymentAgencyAnalyst"
    CREDITOR_ANALYST = "CreditorAnalyst"
    STATE_COORDINATOR = "StateCoordinator"
    REFUND_OFFICER = "RefundOfficer"
    AUDITOR = "Auditor"
    SYSTEM = "System"  # never callable via X-User-Role (PRD §2.1)


class CreditorType(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"


class TinType(str, Enum):
    SSN = "SSN"
    EIN = "EIN"


class PaymentType(str, Enum):
    VENDOR = "VENDOR"
    SALARY = "SALARY"
    BENEFIT_RETIREMENT = "BENEFIT_RETIREMENT"
    BENEFIT_DISABILITY = "BENEFIT_DISABILITY"
    TAX_REFUND = "TAX_REFUND"
    GRANT = "GRANT"


class ExemptionClass(str, Enum):
    EXEMPT = "EXEMPT"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class ExemptionPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DebtType(str, Enum):
    CHILD_SUPPORT = "CHILD_SUPPORT"
    FEDERAL_TAX = "FEDERAL_TAX"
    FEDERAL_NONTAX = "FEDERAL_NONTAX"
    STATE_TAX = "STATE_TAX"
    STATE_OTHER = "STATE_OTHER"


class DebtStatus(str, Enum):
    REFERRED = "REFERRED"
    NOTICED = "NOTICED"
    ACTIVE = "ACTIVE"
    IN_COLLECTION = "IN_COLLECTION"
    PAID_IN_FULL = "PAID_IN_FULL"
    RETURNED = "RETURNED"


class PaymentFileStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"


class PaymentMethod(str, Enum):
    EFT = "EFT"
    CHECK = "CHECK"


class PaymentProcessingStatus(str, Enum):
    VERIFIED = "VERIFIED"
    HELD = "HELD"
    EVALUATED = "EVALUATED"
    EXECUTED = "EXECUTED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class PaymentIntegrityStatus(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"


class OffsetStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"
    REFUNDED = "REFUNDED"
    DROPPED = "DROPPED"


class RefundReason(str, Enum):
    DEBT_NOT_OWED = "DEBT_NOT_OWED"
    AMOUNT_INCORRECT = "AMOUNT_INCORRECT"
    PAYMENT_DUPLICATED = "PAYMENT_DUPLICATED"
    DEBTOR_MISIDENTIFIED = "DEBTOR_MISIDENTIFIED"


class RefundDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class RefundClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class CollectionActionType(str, Enum):
    AWG = "AWG"
    CROSS_SERVICING = "CROSS_SERVICING"


class CollectionActionStatus(str, Enum):
    INITIATED = "INITIATED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class AgreementDirection(str, Enum):
    FED_TO_STATE = "FED_TO_STATE"
    STATE_TO_FED = "STATE_TO_FED"
    BIDIRECTIONAL = "BIDIRECTIONAL"


class ReciprocalAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class DnpListSource(str, Enum):
    DEATH_MASTER_FILE = "DEATH_MASTER_FILE"
    SAM_EXCLUSION = "SAM_EXCLUSION"
    DEBARMENT_LIST = "DEBARMENT_LIST"


class DoNotPayRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ReverseOffsetRequestStatus(str, Enum):
    MATCHED = "MATCHED"
    NO_MATCH = "NO_MATCH"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"


# --- Entity TypedDicts (all carry PRD §2.5 common fields) -----------------------

class CreditorAgency(TypedDict, total=False):
    id: str
    creditor_code: str
    legal_name: str
    creditor_type: str
    state_code: Optional[str]
    remitted_gross_ytd_cents: int
    remitted_ytd_year: Optional[int]
    remitted_net_total_cents: int
    outstanding_receivable_cents: int
    created_at: str
    updated_at: str
    version: int


class Payee(TypedDict, total=False):
    id: str
    tin: str
    tin_type: str
    legal_name: str
    routing_number: Optional[str]
    account_last4: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExemptionPolicy(TypedDict, total=False):
    id: str
    payment_type: str
    exemption_class: str
    protected_minimum_cents: Optional[int]
    max_offset_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Debt(TypedDict, total=False):
    id: str
    creditor_agency_id: str
    debtor_tin: str
    debtor_name: str
    debt_type: str
    original_amount_cents: int
    current_balance_cents: int
    priority_rank: int
    delinquent_since: str
    notice_sent_at: Optional[str]
    due_process_completed: bool
    returned_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentFile(TypedDict, total=False):
    id: str
    agency_code: str
    settlement_date: str
    status: str
    payment_count: int
    total_offset_cents: int
    total_disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    payment_file_id: str
    payee_id: str
    payee_tin: str
    amount_cents: int
    payment_type: str
    payment_method: str
    processing_status: str
    integrity_status: str
    projected_offset_cents: int
    total_offset_cents: int
    disbursed_cents: int
    executed_by_user_id: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Offset(TypedDict, total=False):
    id: str
    payment_id: str
    debt_id: str
    priority_rank: int
    offset_amount_cents: int
    fee_cents: Optional[int]
    net_remittance_cents: Optional[int]
    applied_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundClaim(TypedDict, total=False):
    id: str
    offset_id: str
    claimed_amount_cents: int
    reason: str
    status: str
    appeal_count: int
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    refund_amount_cents: Optional[int]
    clawback_cents: Optional[int]
    treasury_absorbed_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CollectionAgency(TypedDict, total=False):
    id: str
    agency_code: str
    name: str
    capacity_max_active: int
    created_at: str
    updated_at: str
    version: int


class CollectionAction(TypedDict, total=False):
    id: str
    debt_id: str
    collection_agency_id: Optional[str]
    action_type: str
    notice_sent_at: Optional[str]
    disposable_pay_estimate_cents: Optional[int]
    projected_per_period_cents: Optional[int]
    collected_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReverseOffsetMatch(TypedDict, total=False):
    debt_id: str
    matched_amount_cents: int


class ReverseOffsetRequest(TypedDict, total=False):
    id: str
    state_code: str
    payee_tin: str
    requested_amount_cents: int
    status: str
    matches: List[ReverseOffsetMatch]
    matched_total_cents: int
    expires_at: str
    confirmed_at: Optional[str]
    applied_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ReciprocalAgreement(TypedDict, total=False):
    id: str
    state_code: str
    direction: str
    effective_from: str
    effective_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DoNotPayRecord(TypedDict, total=False):
    id: str
    tin: str
    list_source: str
    effective_from: str
    effective_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


__all__ = [name for name in dir() if not name.startswith("_")]
