"""Domain types for the Credit Balance & Refund Management API.

Entity TypedDicts, status enums and the operating-role enum, all named with the
field names the PRD uses.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CREDIT_ANALYST = "CreditAnalyst"
    REFUND_APPROVER = "RefundApprover"
    DISBURSEMENT_OFFICER = "DisbursementOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PAYER_LIAISON = "PayerLiaison"
    SYSTEM_ADMIN = "SystemAdmin"


class PayerType(str, Enum):
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    COMMERCIAL = "COMMERCIAL"
    TRICARE = "TRICARE"
    SELF_PAY = "SELF_PAY"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    BAD_DEBT = "BAD_DEBT"


class FinancialClass(str, Enum):
    INPATIENT = "INPATIENT"
    OUTPATIENT = "OUTPATIENT"
    EMERGENCY = "EMERGENCY"


class StateCode(str, Enum):
    CA = "CA"
    TX = "TX"
    NY = "NY"
    FL = "FL"


class TxnType(str, Enum):
    CHARGE = "CHARGE"
    PAYMENT = "PAYMENT"
    CONTRACTUAL_ADJUSTMENT = "CONTRACTUAL_ADJUSTMENT"
    REFUND_DISBURSEMENT = "REFUND_DISBURSEMENT"
    TAKE_BACK_OFFSET = "TAKE_BACK_OFFSET"
    ESCHEAT_REMITTANCE = "ESCHEAT_REMITTANCE"
    REVERSAL = "REVERSAL"


class TxnSource(str, Enum):
    PATIENT = "PATIENT"
    PAYER = "PAYER"
    SYSTEM = "SYSTEM"


class CreditBalanceStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ATTRIBUTED = "ATTRIBUTED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    RESOLVED_BY_OFFSET = "RESOLVED_BY_OFFSET"
    ESCHEATED = "ESCHEATED"
    WRITTEN_OFF = "WRITTEN_OFF"


class AttributionMethod(str, Enum):
    PROPORTIONAL = "PROPORTIONAL"
    REVERSE_CHRONOLOGICAL = "REVERSE_CHRONOLOGICAL"


class Attribution(str, Enum):
    PATIENT = "PATIENT"
    PAYER = "PAYER"
    SPLIT = "SPLIT"
    UNDETERMINED = "UNDETERMINED"


class AgingBucket(str, Enum):
    D0_30 = "D0_30"
    D31_60 = "D31_60"
    D61_90 = "D61_90"
    D91_180 = "D91_180"
    OVER_180 = "OVER_180"


class CauseCode(str, Enum):
    DUPLICATE_PAYMENT = "DUPLICATE_PAYMENT"
    CONTRACTUAL_UNDER_ADJUSTMENT = "CONTRACTUAL_UNDER_ADJUSTMENT"
    WRONG_ACCOUNT_POSTING = "WRONG_ACCOUNT_POSTING"
    COB_PRIMARY_SECONDARY = "COB_PRIMARY_SECONDARY"
    ESTIMATE_OVERCOLLECTION = "ESTIMATE_OVERCOLLECTION"
    RETRO_ELIGIBILITY_CHANGE = "RETRO_ELIGIBILITY_CHANGE"


class CorrectiveAction(str, Enum):
    REPOST_TRANSACTION = "REPOST_TRANSACTION"
    UPDATE_CONTRACT_TERMS = "UPDATE_CONTRACT_TERMS"
    STAFF_RETRAINING = "STAFF_RETRAINING"
    PAYER_ESCALATION = "PAYER_ESCALATION"
    NONE = "NONE"


class ApprovalState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    CANCELLED = "CANCELLED"


class DisbursementState(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    BATCHED = "BATCHED"
    ISSUED = "ISSUED"
    CLEARED = "CLEARED"
    REISSUE_PENDING = "REISSUE_PENDING"
    VOID_CLOSED = "VOID_CLOSED"


class PayeeType(str, Enum):
    PATIENT = "PATIENT"
    PAYER = "PAYER"


class Decision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"


class BatchState(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"


class BankAccountCode(str, Enum):
    OPERATING = "OPERATING"
    TRUST = "TRUST"
    ESCROW = "ESCROW"


class CheckState(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    CLEARED = "CLEARED"
    VOIDED = "VOIDED"
    STALE = "STALE"
    REISSUED = "REISSUED"
    ESCHEATED = "ESCHEATED"


class VoidReason(str, Enum):
    STALE_DATED = "STALE_DATED"
    WRONG_PAYEE = "WRONG_PAYEE"
    BATCH_ERROR = "BATCH_ERROR"
    PAYER_REQUEST = "PAYER_REQUEST"


class NoticeState(str, Enum):
    RECEIVED = "RECEIVED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    FULLY_APPLIED = "FULLY_APPLIED"
    DISPUTED = "DISPUTED"
    WITHDRAWN = "WITHDRAWN"


class OffsetState(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class ObligationState(str, Enum):
    OPEN = "OPEN"
    LATE = "LATE"
    REPORTED = "REPORTED"
    REPORTED_LATE = "REPORTED_LATE"
    SATISFIED = "SATISFIED"
    SATISFIED_LATE = "SATISFIED_LATE"
    SATISFIED_BY_OFFSET = "SATISFIED_BY_OFFSET"


class SatisfactionMode(str, Enum):
    REFUND_CHECK = "REFUND_CHECK"
    OFFSET = "OFFSET"
    WRITE_OFF = "WRITE_OFF"


class EscheatmentState(str, Enum):
    DORMANT = "DORMANT"
    DUE_DILIGENCE_SENT = "DUE_DILIGENCE_SENT"
    CLAIMED = "CLAIMED"
    REMITTED = "REMITTED"
    EXEMPT = "EXEMPT"


class EscheatBasis(str, Enum):
    ISSUE_DATE = "ISSUE_DATE"
    LAST_CONTACT = "LAST_CONTACT"


class ContactMethod(str, Enum):
    FIRST_CLASS_MAIL = "FIRST_CLASS_MAIL"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    EMAIL = "EMAIL"


class ReportType(str, Enum):
    CREDIT_BALANCE_LIABILITY = "CREDIT_BALANCE_LIABILITY"
    MEDICARE_CBR = "MEDICARE_CBR"
    ESCHEAT_HOLDER_REPORT = "ESCHEAT_HOLDER_REPORT"


class ReportState(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


# --- Entity shapes -----------------------------------------------------------
# Resources that carry id + created_at + updated_at + version.

class Payer(TypedDict):
    id: str
    name: str
    payer_code: str
    payer_type: str
    take_back_allowed: bool
    refund_remit_days: int
    created_at: str
    updated_at: str
    version: int


class PatientAccount(TypedDict):
    id: str
    account_number: str
    mrn: str
    patient_name: str
    guarantor_state_code: str
    primary_payer_id: str
    financial_class: str
    discharge_date: Optional[str]
    balance_cents: int
    credit_balance_cents: int
    last_activity_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditBalance(TypedDict):
    id: str
    account_id: str
    payer_id: str
    credit_amount_cents: int
    identified_at: str
    attribution_method: Optional[str]
    attribution: Optional[str]
    patient_portion_cents: int
    payer_portion_cents: int
    refunded_cents: int
    offset_cents: int
    outstanding_cents: int
    aging_days: int
    aging_bucket: str
    root_cause_confirmed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RootCauseFinding(TypedDict):
    id: str
    credit_balance_id: str
    cause_code: str
    corrective_action: str
    evidence_transaction_ids: List[str]
    narrative: str
    analyst_user_id: str
    confirmed: bool
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict):
    id: str
    credit_balance_id: str
    requested_amount_cents: int
    approved_amount_cents: int
    payee_type: str
    payee_name: str
    payee_address_line: str
    payee_state_code: str
    prepared_by_user_id: str
    required_approval_tier: int
    required_approval_count: int
    approvals_received: int
    revision_count: int
    last_decision_user_id: Optional[str]
    approval_state: str
    disbursement_state: str
    created_at: str
    updated_at: str
    version: int


class RefundBatch(TypedDict):
    id: str
    batch_number: str
    bank_account_code: str
    cutoff_at: str
    scheduled_run_at: str
    item_count: int
    total_gross_cents: int
    total_fee_cents: int
    total_net_cents: int
    state: str
    created_at: str
    updated_at: str
    version: int


class CheckDisbursement(TypedDict):
    id: str
    refund_request_id: str
    refund_batch_id: str
    reissue_of_disbursement_id: Optional[str]
    check_number: Optional[str]
    gross_amount_cents: int
    processing_fee_cents: int
    net_check_amount_cents: int
    payee_state_code: str
    issued_at: Optional[str]
    cleared_at: Optional[str]
    stale_at: Optional[str]
    void_reason: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class TakeBackNotice(TypedDict):
    id: str
    payer_id: str
    notice_number: str
    total_recoup_cents: int
    admin_fee_cents: int
    received_at: str
    dispute_deadline_at: str
    applied_cents: int
    remaining_unapplied_cents: int
    state: str
    created_at: str
    updated_at: str
    version: int


class OffsetApplication(TypedDict):
    id: str
    take_back_notice_id: str
    account_id: str
    credit_balance_id: str
    posted_transaction_id: str
    applied_cents: int
    admin_fee_share_cents: int
    sequence: int
    applied_at: str
    reversed_at: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class MedicareRepaymentObligation(TypedDict):
    id: str
    credit_balance_id: str
    payer_id: str
    identified_at: str
    due_at: str
    reportable_amount_cents: int
    days_elapsed: int
    days_late: int
    penalty_cents: int
    report_reference: Optional[str]
    reported_at: Optional[str]
    satisfied_at: Optional[str]
    satisfaction_mode: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class EscheatmentRecord(TypedDict):
    id: str
    check_disbursement_id: str
    basis: str
    state_code: str
    dormancy_days: int
    dormancy_start_at: str
    escheat_due_at: str
    due_diligence_open_at: str
    contact_method: Optional[str]
    due_diligence_sent_at: Optional[str]
    remitted_amount_cents: int
    claimed_at: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict):
    id: str
    report_type: str
    scope_code: str
    period_start_at: str
    period_end_at: str
    as_of_at: str
    total_liability_cents: int
    patient_liability_cents: int
    payer_liability_cents: int
    medicare_at_risk_cents: int
    over_180_count: int
    line_count: int
    generated_by_user_id: str
    state: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only audit records: id + created_at only -------------------------

class AccountTransaction(TypedDict):
    id: str
    account_id: str
    txn_type: str
    amount_cents: int
    source: str
    payer_id: Optional[str]
    posted_at: str
    effective_at: str
    reversal_of_transaction_id: Optional[str]
    is_reversed: bool
    remark: Optional[str]
    created_at: str


class RefundApproval(TypedDict):
    id: str
    refund_request_id: str
    approver_user_id: str
    approver_tier: int
    decision: str
    note: Optional[str]
    decided_at: str
    created_at: str
