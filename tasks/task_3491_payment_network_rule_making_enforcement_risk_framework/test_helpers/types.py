"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow PRD §2.5: most resources carry id + created_at + updated_at +
version. Three immutable record types — SettlementWindow, ReturnRecord,
AccountValidation — carry ONLY id and created_at; their TypedDicts omit
updated_at and version entirely.
"""

from enum import Enum
from typing import Optional, TypedDict


# =============================================================================
# Enums
# =============================================================================


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PARTICIPANT_OFFICER = "ParticipantOfficer"
    VOTING_DELEGATE = "VotingDelegate"
    AUDITOR = "Auditor"


class ParticipantType(str, Enum):
    ODFI = "ODFI"
    RDFI = "RDFI"
    BOTH = "BOTH"


class ParticipantStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class OriginatorStatus(str, Enum):
    PENDING_DUE_DILIGENCE = "PENDING_DUE_DILIGENCE"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RiskTier(str, Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class EntryClass(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AuthorizationType(str, Enum):
    WRITTEN_SIGNED = "WRITTEN_SIGNED"
    ORAL_RECORDED = "ORAL_RECORDED"
    IMPLIED = "IMPLIED"
    NONE = "NONE"


class RuleProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMENT_OPEN = "COMMENT_OPEN"
    BALLOTING = "BALLOTING"
    PASSED = "PASSED"
    REJECTED = "REJECTED"
    RETURNED_FOR_REWORK = "RETURNED_FOR_REWORK"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class BallotOutcome(str, Enum):
    PASSED_QUORUM = "PASSED_QUORUM"
    REJECTED_VOTE = "REJECTED_VOTE"
    REJECTED_NO_QUORUM = "REJECTED_NO_QUORUM"


class Vote(str, Enum):
    YEA = "YEA"
    NAY = "NAY"
    ABSTAIN = "ABSTAIN"


class BallotStatus(str, Enum):
    CAST = "CAST"
    LOCKED = "LOCKED"


class GuidanceDocumentStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class PaymentEntryStatus(str, Enum):
    ORIGINATED = "ORIGINATED"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class ReturnReasonCode(str, Enum):
    UNAUTHORIZED_DEBIT = "UNAUTHORIZED_DEBIT"
    AUTHORIZATION_REVOKED = "AUTHORIZATION_REVOKED"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    INVALID_ACCOUNT = "INVALID_ACCOUNT"
    STOP_PAYMENT = "STOP_PAYMENT"


class ReturnReasonClass(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    OTHER = "OTHER"


# PRD §3.7 reason_code -> reason_class derivation.
REASON_CLASS_BY_CODE = {
    ReturnReasonCode.UNAUTHORIZED_DEBIT.value: ReturnReasonClass.UNAUTHORIZED.value,
    ReturnReasonCode.AUTHORIZATION_REVOKED.value: ReturnReasonClass.UNAUTHORIZED.value,
    ReturnReasonCode.INSUFFICIENT_FUNDS.value: ReturnReasonClass.ADMINISTRATIVE.value,
    ReturnReasonCode.INVALID_ACCOUNT.value: ReturnReasonClass.ADMINISTRATIVE.value,
    ReturnReasonCode.STOP_PAYMENT.value: ReturnReasonClass.OTHER.value,
}


class ValidationMethod(str, Enum):
    MICRO_DEPOSIT = "MICRO_DEPOSIT"
    PRENOTE = "PRENOTE"
    COMMERCIAL_SERVICE = "COMMERCIAL_SERVICE"
    PRIOR_HISTORY = "PRIOR_HISTORY"


class AccountValidationStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class ReturnRateSnapshotStatus(str, Enum):
    COMPUTED = "COMPUTED"


class InquiryReturnClass(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    OVERALL = "OVERALL"


class InquiryCaseStatus(str, Enum):
    OPENED = "OPENED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class ViolationCode(str, Enum):
    EXCESSIVE_UNAUTHORIZED_RETURNS = "EXCESSIVE_UNAUTHORIZED_RETURNS"
    EXCESSIVE_ADMINISTRATIVE_RETURNS = "EXCESSIVE_ADMINISTRATIVE_RETURNS"
    MISSING_ACCOUNT_VALIDATION = "MISSING_ACCOUNT_VALIDATION"
    LATE_ATTESTATION = "LATE_ATTESTATION"
    AUDIT_NONCOMPLIANCE = "AUDIT_NONCOMPLIANCE"


# PRD §3.8 inquiry return_class -> violation_code derivation on escalation.
VIOLATION_CODE_BY_RETURN_CLASS = {
    InquiryReturnClass.UNAUTHORIZED.value: ViolationCode.EXCESSIVE_UNAUTHORIZED_RETURNS.value,
    InquiryReturnClass.ADMINISTRATIVE.value: ViolationCode.EXCESSIVE_ADMINISTRATIVE_RETURNS.value,
    InquiryReturnClass.OVERALL.value: ViolationCode.EXCESSIVE_UNAUTHORIZED_RETURNS.value,
}


class EnforcementActionStatus(str, Enum):
    ISSUED = "ISSUED"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    WITHDRAWN = "WITHDRAWN"
    PAID = "PAID"


class ComplianceAttestationStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    OVERDUE = "OVERDUE"


class AuditReportStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# =============================================================================
# Entity TypedDicts — common_fields: true (id + created_at + updated_at + version)
# =============================================================================


class Participant(TypedDict):
    id: str
    legal_name: str
    participant_type: str
    routing_number: str
    status: str
    current_period: Optional[str]  # null until first settlement accrual
    current_period_fees_cents: int
    created_at: str
    updated_at: str
    version: int


class Originator(TypedDict):
    id: str
    participant_id: str
    legal_name: str
    risk_tier: str
    exposure_limit_cents: int
    committed_exposure_cents: int
    contingent_exposure_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransactionCode(TypedDict):
    id: str
    code: str
    entry_class: str
    authorization_requirement: str
    return_timeframe_banking_days: int
    account_validation_required: bool
    warranty_obligations: str
    created_at: str
    updated_at: str
    version: int


class RuleProposal(TypedDict):
    id: str
    transaction_code_id: str
    title: str
    summary: str
    effective_date: str
    status: str
    outcome: Optional[str]  # null until close-ballot
    comment_opened_at: Optional[str]  # null until COMMENT_OPEN
    ballot_opened_at: Optional[str]  # null until BALLOTING
    yea_count: int
    nay_count: int
    abstain_count: int
    created_at: str
    updated_at: str
    version: int


class Ballot(TypedDict):
    id: str
    rule_proposal_id: str
    participant_id: str
    vote: str
    status: str
    cast_at: str
    created_at: str
    updated_at: str
    version: int


class GuidanceDocument(TypedDict):
    id: str
    rule_proposal_id: str
    transaction_code_id: str
    title: str
    body_ref: str
    effective_from: str
    effective_until: Optional[str]  # null means open-ended
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentEntry(TypedDict):
    id: str
    originator_id: str
    originating_participant_id: str
    transaction_code_id: str
    settlement_window_id: str
    amount_cents: int
    receiver_account_number_hash: str
    receiver_name: str
    authorization_type: str
    same_day: bool
    entry_fee_cents: Optional[int]  # null until SETTLED
    status: str
    settled_at: Optional[str]  # null until SETTLED
    settled_date: Optional[str]  # null until SETTLED
    created_at: str
    updated_at: str
    version: int


class ReturnRateSnapshot(TypedDict):
    id: str
    participant_id: str
    period: str
    forward_count: int
    origination_forward_count: int
    unauth_return_count: int
    admin_return_count: int
    other_return_count: int
    origination_unauth_count: int
    origination_admin_count: int
    settlement_unauth_rate: float
    settlement_admin_rate: float
    settlement_overall_rate: float
    origination_unauth_rate: float
    origination_admin_rate: float
    unauth_breach: bool
    admin_breach: bool
    overall_breach: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InquiryCase(TypedDict):
    id: str
    participant_id: str
    return_rate_snapshot_id: str
    return_class: str
    response_deadline: str
    response_text: Optional[str]  # null until respond
    status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict):
    id: str
    participant_id: str
    inquiry_case_id: Optional[str]  # null for direct filings
    violation_code: str
    escalation_tier: int
    fine_base_cents: int
    fine_total_cents: Optional[int]  # null until PAID
    escalated_by_user_id: Optional[str]  # null for direct filings
    issued_date: str
    paid_at: Optional[str]  # null until PAID
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceAttestation(TypedDict):
    id: str
    participant_id: str
    period_year: int
    due_date: str
    submitted_at: Optional[str]  # null until first submission
    late_submission: bool
    attestation_text: Optional[str]  # null until submission
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditReport(TypedDict):
    id: str
    participant_id: str
    start_date: str
    end_date: str
    findings_count: Optional[int]  # null until COMPLETED
    created_by_user_id: str
    completed_by_user_id: Optional[str]  # null until COMPLETED
    status: str
    created_at: str
    updated_at: str
    version: int


# =============================================================================
# Entity TypedDicts — common_fields: false (ONLY id + created_at; no updated_at,
# no version — PRD §2.5)
# =============================================================================


class SettlementWindow(TypedDict):
    id: str
    window_code: str
    cutoff_time_utc: str
    per_entry_limit_cents: int
    odfi_window_cap_cents: int
    created_at: str


class ReturnRecord(TypedDict):
    id: str
    payment_entry_id: str
    returning_participant_id: str
    reason_code: str
    reason_class: str
    returned_at: str
    created_at: str


class AccountValidation(TypedDict):
    id: str
    originator_id: str
    account_number_hash: str
    method: str
    validated_until: str
    status: str
    created_at: str
