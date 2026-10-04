"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the common system-managed fields (id, created_at,
updated_at, version) described in PRD section 2.5.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CLEARINGHOUSE_OPS = "ClearinghouseOps"
    REGISTRAR_SUBMITTER = "RegistrarSubmitter"
    REGISTRAR_CERTIFIER = "RegistrarCertifier"
    REQUESTER = "Requester"
    LEARNER = "Learner"
    SERVICER = "Servicer"
    RESEARCH_ANALYST = "ResearchAnalyst"


class InstitutionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    OPS = "OPS"
    AGREEMENT_LAPSE = "AGREEMENT_LAPSE"


class ComplianceStanding(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    NON_COMPLIANT = "NON_COMPLIANT"


class AgreementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class InstitutionUserRole(str, Enum):
    SUBMITTER = "SUBMITTER"
    CERTIFIER = "CERTIFIER"


class InstitutionUserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class PeriodStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    GRACE = "GRACE"
    CLOSED = "CLOSED"


class PeriodOutcome(str, Enum):
    NONE = "NONE"
    ON_TIME = "ON_TIME"
    LATE = "LATE"
    DELINQUENT = "DELINQUENT"


class DefermentStanding(str, Enum):
    NONE = "NONE"
    DEFERMENT_ELIGIBLE = "DEFERMENT_ELIGIBLE"
    DEFERMENT_INELIGIBLE = "DEFERMENT_INELIGIBLE"
    WITHDRAWN_GRACE = "WITHDRAWN_GRACE"
    REPAYMENT_DUE = "REPAYMENT_DUE"


class DirectiveType(str, Enum):
    FULL_BLOCK = "FULL_BLOCK"
    DIRECTORY_BLOCK = "DIRECTORY_BLOCK"
    RESEARCH_OPT_OUT = "RESEARCH_OPT_OUT"


class DirectiveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class FileStatus(str, Enum):
    UPLOADED = "UPLOADED"
    CERTIFIED = "CERTIFIED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    SUPERSEDED = "SUPERSEDED"


class EntryStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RejectReason(str, Enum):
    NONE = "NONE"
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_ENUM_VALUE = "INVALID_ENUM_VALUE"
    INVALID_CREDITS = "INVALID_CREDITS"
    INVALID_TERM_DATES = "INVALID_TERM_DATES"
    INVALID_WITHDRAWAL_DATE = "INVALID_WITHDRAWAL_DATE"
    DUPLICATE_STUDENT_IN_FILE = "DUPLICATE_STUDENT_IN_FILE"


class StatusCode(str, Enum):
    NONE = "NONE"
    FULL_TIME = "FULL_TIME"
    HALF_TIME = "HALF_TIME"
    LESS_THAN_HALF_TIME = "LESS_THAN_HALF_TIME"
    WITHDRAWN = "WITHDRAWN"


class CareerLevel(str, Enum):
    UNDERGRAD = "UNDERGRAD"
    GRADUATE = "GRADUATE"


class CaseStatus(str, Enum):
    FILED = "FILED"
    APPLIED = "APPLIED"
    DENIED = "DENIED"


class ReasonCode(str, Enum):
    REPORTING_ERROR = "REPORTING_ERROR"
    STATUS_MISSTATEMENT = "STATUS_MISSTATEMENT"
    LATE_WITHDRAWAL_NOTICE = "LATE_WITHDRAWAL_NOTICE"


class DecisionOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DegreeLevel(str, Enum):
    CERTIFICATE = "CERTIFICATE"
    ASSOCIATE = "ASSOCIATE"
    BACHELOR = "BACHELOR"
    MASTER = "MASTER"
    DOCTORATE = "DOCTORATE"


class DegreeStatus(str, Enum):
    REPORTED = "REPORTED"
    SEALED = "SEALED"
    REVOKED = "REVOKED"


class RequesterKind(str, Enum):
    EMPLOYER = "EMPLOYER"
    BACKGROUND_SCREENER = "BACKGROUND_SCREENER"


class RequesterStatus(str, Enum):
    PENDING_VETTING = "PENDING_VETTING"
    VETTED = "VETTED"
    SUSPENDED = "SUSPENDED"
    DENIED = "DENIED"


class VetOutcome(str, Enum):
    VET = "VET"
    DENY = "DENY"


class ProductType(str, Enum):
    DEGREE = "DEGREE"
    ENROLLMENT = "ENROLLMENT"
    TRANSCRIPT = "TRANSCRIPT"


class Purpose(str, Enum):
    EMPLOYMENT = "EMPLOYMENT"
    BACKGROUND_SCREEN = "BACKGROUND_SCREEN"
    LOAN_DEFERMENT = "LOAN_DEFERMENT"
    INSURANCE = "INSURANCE"
    SELF = "SELF"


class RequestStatus(str, Enum):
    QUOTED = "QUOTED"
    PAID = "PAID"
    RELEASED = "RELEASED"
    BLOCKED_PRIVACY = "BLOCKED_PRIVACY"
    NO_RECORD = "NO_RECORD"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class VolumeTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"


class ResultStatus(str, Enum):
    NONE = "NONE"
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"


class NotificationStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUPERSEDED = "SUPERSEDED"


class DatasetStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GENERATED = "GENERATED"


class Institution(TypedDict, total=False):
    id: str
    name: str
    ope_id: str
    status: str
    suspension_reason: str
    compliance_standing: str
    users: list
    created_at: str
    updated_at: str
    version: int


class ParticipationAgreement(TypedDict):
    id: str
    institution_id: str
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InstitutionUser(TypedDict):
    id: str
    institution_id: str
    email: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReportingPeriod(TypedDict):
    id: str
    institution_id: str
    term_label: str
    term_start: str
    term_end: str
    submission_opens_at: str
    submission_due_at: str
    grace_ends_at: str
    status: str
    outcome: str
    upload_count: int
    created_at: str
    updated_at: str
    version: int


class StudentRecord(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    deferment_standing: str
    created_at: str
    updated_at: str
    version: int


class PrivacyDirective(TypedDict):
    id: str
    student_id: str
    directive_type: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EnrollmentFile(TypedDict):
    id: str
    institution_id: str
    reporting_period_id: str
    submitted_by_user_id: str
    row_count: int
    accepted_rows: int
    rejected_rows: int
    status: str
    certified_at: Optional[str]
    late_submission: bool
    open_correction_count: int
    created_at: str
    updated_at: str
    version: int


class EnrollmentEntry(TypedDict):
    id: str
    file_id: str
    institution_id: str
    student_id: str
    student_ref: str
    row_index: int
    credit_hours: float
    career_level: str
    term_start: str
    term_end: str
    withdrawal_date: Optional[str]
    servicer_ref: Optional[str]
    entry_status: str
    reject_reason: str
    status_code: str
    census_status_code: str
    deferment_status: str
    source_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectionCase(TypedDict):
    id: str
    enrollment_entry_id: str
    filed_by_user_id: str
    corrected_credit_hours: Optional[float]
    corrected_withdrawal_date: Optional[str]
    clear_withdrawal_date: bool
    reason_code: str
    status: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DegreeRecord(TypedDict):
    id: str
    institution_id: str
    student_id: str
    degree_level: str
    degree_title: str
    conferred_on: str
    status: str
    sealed_at: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Requester(TypedDict):
    id: str
    org_name: str
    requester_kind: str
    status: str
    credit_balance_cents: int
    initial_credit_cents: int
    vetted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationRequest(TypedDict):
    id: str
    requester_id: Optional[str]
    student_id: str
    institution_id: str
    product_type: str
    purpose: str
    consent_artifact: bool
    rush: bool
    status: str
    fee_cents: int
    volume_tier_at_quote: str
    quote_expires_at: str
    paid_at: Optional[str]
    released_at: Optional[str]
    result_status: str
    enrollment_status_at_release: str
    artifact_expires_at: Optional[str]
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class ServicerNotification(TypedDict):
    id: str
    enrollment_entry_id: str
    student_id: str
    servicer_ref: str
    notification_type: str
    grace_end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ResearchDataset(TypedDict):
    id: str
    scope_institution_id: str
    created_by_analyst_id: str
    cohort_term_start: str
    cohort_term_end: str
    status: str
    cohort_size: int
    completer_count: int
    adjusted_cohort_size: int
    completion_rate_census: float
    completion_rate_adjusted: float
    generated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
