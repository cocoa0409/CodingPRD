"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this registry carry the full common spine (id, created_at,
updated_at, version) — there are no append-only resources.
"""
from enum import Enum
from typing import Optional, TypedDict


class MemberStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"


class OrgIdType(str, Enum):
    TAX_ID = "TAX_ID"
    CHARTER_NUMBER = "CHARTER_NUMBER"
    LEI = "LEI"


class MemberType(str, Enum):
    ORIGINATOR = "ORIGINATOR"
    SERVICER = "SERVICER"
    INVESTOR = "INVESTOR"
    SUBSERVICER = "SUBSERVICER"
    CUSTODIAN = "CUSTODIAN"


class SignerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class RoleScope(str, Enum):
    REGISTRATION = "REGISTRATION"
    TRANSFER = "TRANSFER"
    FORECLOSURE = "FORECLOSURE"
    ALL = "ALL"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FORECLOSING = "FORECLOSING"
    INACTIVE_ASSIGNED_OUT = "INACTIVE_ASSIGNED_OUT"
    INACTIVE_TERMINATED = "INACTIVE_TERMINATED"
    INACTIVE_SATISFIED = "INACTIVE_SATISFIED"


class ForeclosureMode(str, Enum):
    ASSIGN_OUT_REQUIRED = "ASSIGN_OUT_REQUIRED"
    IN_REGISTRY_ALLOWED = "IN_REGISTRY_ALLOWED"


class TransferType(str, Enum):
    BENEFICIAL = "BENEFICIAL"
    SERVICING = "SERVICING"
    BOTH = "BOTH"


class TransferStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class MatchStatus(str, Enum):
    MATCHED = "MATCHED"
    PENDING = "PENDING"
    EXPIRED = "EXPIRED"
    WAIVED = "WAIVED"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    SETTLED = "SETTLED"


class FindingFieldName(str, Enum):
    MIN = "MIN"
    CURRENT_SERVICER = "CURRENT_SERVICER"
    CURRENT_INVESTOR = "CURRENT_INVESTOR"
    PROPERTY_STATE = "PROPERTY_STATE"
    CLOSING_DATE = "CLOSING_DATE"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class ReportStatus(str, Enum):
    FINAL = "FINAL"
    VOID = "VOID"


class StandingBand(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    DISENGAGEMENT_ELIGIBLE = "DISENGAGEMENT_ELIGIBLE"


class SanctionStatus(str, Enum):
    ASSESSED = "ASSESSED"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    REDUCED = "REDUCED"
    VACATED = "VACATED"
    PAID = "PAID"


class RunStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ExceptionType(str, Enum):
    REGISTRY_ONLY = "REGISTRY_ONLY"
    PLATFORM_ONLY = "PLATFORM_ONLY"
    FIELD_MISMATCH = "FIELD_MISMATCH"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class UserRole(str, Enum):
    REGISTRY_ADMIN = "RegistryAdmin"
    MEMBER_REP = "MemberRep"
    QA_AUDITOR = "QAAuditor"
    BORROWER_INQUIRER = "BorrowerInquirer"


class Member(TypedDict):
    id: str
    legal_name: str
    org_id: str
    org_id_type: str
    member_type: str
    termination_effective_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuthorizedSigner(TypedDict):
    id: str
    member_id: str
    full_name: str
    email: str
    effective_from: str
    effective_until: Optional[str]
    role_scope: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RegisteredLoan(TypedDict):
    id: str
    min: str
    serial: int
    registering_member_id: str
    loan_amount_cents: int
    property_state: str
    closing_date: str
    foreclosure_mode: str
    current_investor_id: str
    current_servicer_id: str
    status: str
    assigned_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transfer(TypedDict):
    id: str
    loan_id: str
    from_member_id: str
    to_member_id: str
    transfer_type: str
    effective_date: str
    idempotency_key: str
    days_late: int
    late_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferMatch(TypedDict):
    id: str
    transfer_id: str
    reported_by_member_id: str
    reported_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QAReview(TypedDict):
    id: str
    member_id: str
    period_start: str
    period_end: str
    sample_size: int
    discrepancy_score: float
    status: str
    created_by: str
    settled_by: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QAFinding(TypedDict):
    id: str
    review_id: str
    loan_id: str
    field_name: str
    expected_value: str
    actual_value: str
    severity: str
    created_at: str
    updated_at: str
    version: int


class AnnualReport(TypedDict):
    id: str
    member_id: str
    report_year: int
    reporting_rate: float
    reporting_rate_amount_weighted: float
    discrepancy_rate: float
    open_exceptions: int
    standing_score: float
    standing_band: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Sanction(TypedDict):
    id: str
    member_id: str
    review_id: str
    total_amount_cents: int
    line_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SORReconciliationRun(TypedDict):
    id: str
    member_id: str
    total_records: int
    matched_count: int
    registry_only_count: int
    platform_only_count: int
    field_mismatch_count: int
    match_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SORException(TypedDict):
    id: str
    run_id: str
    loan_id: Optional[str]
    exception_type: str
    detail: str
    status: str
    created_at: str
    updated_at: str
    version: int
