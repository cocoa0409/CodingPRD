"""Domain types: entity TypedDicts, status enums, role enum.

All shape information here derives from the PRD's resource descriptions
(§2.4 common properties and the §3 entity narratives).
"""
from enum import Enum
from typing import Optional, TypedDict


class ClientStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RiskPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PayrollRunStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IMPOUNDED = "IMPOUNDED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class FundingModel(str, Enum):
    STANDARD = "STANDARD"
    WIRE_REQUIRED = "WIRE_REQUIRED"


class ImpoundStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    RETURNED = "RETURNED"


class FundingFailureKind(str, Enum):
    NSF_RETURN = "NSF_RETURN"
    WIRE_NOT_CONFIRMED = "WIRE_NOT_CONFIRMED"


class DepositStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DepositFrequency(str, Enum):
    SEMIWEEKLY = "SEMIWEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class ReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    RECONCILED = "RECONCILED"
    AMENDED = "AMENDED"
    REJECTED = "REJECTED"


class FilingMethod(str, Enum):
    ELECTRONIC = "ELECTRONIC"
    MANUAL_INTERIM = "MANUAL_INTERIM"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class NoticeStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED_NO_CHANGE = "RESOLVED_NO_CHANGE"
    RESOLVED_ADJUSTMENT = "RESOLVED_ADJUSTMENT"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class NoticeType(str, Enum):
    BALANCE_DUE = "BALANCE_DUE"
    PENALTY_ASSESSMENT = "PENALTY_ASSESSMENT"
    DATA_MISMATCH = "DATA_MISMATCH"
    MISSING_RETURN = "MISSING_RETURN"


class StatementKind(str, Enum):
    ORIGINAL = "ORIGINAL"
    CORRECTION = "CORRECTION"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CORRECTED = "CORRECTED"
    VOIDED = "VOIDED"


class AssessmentTrigger(str, Enum):
    FUNDING_FAILURE = "FUNDING_FAILURE"
    FAILURE_CURED = "FAILURE_CURED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class UserRole(str, Enum):
    CLIENT_PAYROLL_ADMIN = "ClientPayrollAdmin"
    BUREAU_ONBOARDER = "BureauOnboarder"
    BUREAU_TAX_FILER = "BureauTaxFiler"
    BUREAU_TREASURY = "BureauTreasury"
    BUREAU_COMPLIANCE = "BureauCompliance"


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    name: str
    deposit_frequency: str
    penalty_tier1_rate: float
    penalty_tier2_rate: float
    penalty_tier3_rate: float
    underpayment_threshold_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    legal_name: str
    ein: str
    status: str
    risk_posture: str
    funding_failure_count: int
    credit_hold: bool
    onboarded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JurisdictionRegistration(TypedDict, total=False):
    id: str
    client_id: str
    jurisdiction_id: str
    agency_account_number: str
    poa_document_ref: str
    status: str
    verified_at: Optional[str]
    rejected_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollRun(TypedDict, total=False):
    id: str
    client_id: str
    pay_date: str
    period_start: str
    period_end: str
    gross_pay_cents: int
    total_tax_cents: int
    impound_amount_cents: int
    status: str
    funding_model: Optional[str]
    funding_confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Impound(TypedDict, total=False):
    id: str
    payroll_run_id: str
    client_id: str
    amount_cents: int
    initiated_at: str
    due_by: str
    settled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingFailureEvent(TypedDict, total=False):
    # Immutable audit record: only id + created_at plus business fields.
    # No updated_at, no version.
    id: str
    impound_id: str
    client_id: str
    kind: str
    occurred_at: str
    resolved_at: Optional[str]
    strike_count_after: int
    created_at: str


class TaxDeposit(TypedDict, total=False):
    id: str
    client_id: str
    jurisdiction_id: str
    payroll_run_id: str
    amount_cents: int
    due_date: str
    quarter: str
    status: str
    submitted_at: Optional[str]
    confirmed_at: Optional[str]
    late_days: int
    penalty_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict, total=False):
    id: str
    client_id: str
    jurisdiction_id: str
    period: str
    filing_method: str
    status: str
    expected_liability_cents: int
    filed_at: Optional[str]
    reconciled_at: Optional[str]
    supersedes_return_id: Optional[str]
    shortfall_penalty_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class ReturnAmendment(TypedDict, total=False):
    id: str
    return_id: str
    reason: str
    adjusted_liability_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgencyNotice(TypedDict, total=False):
    id: str
    client_id: str
    jurisdiction_id: str
    return_id: str
    notice_type: str
    claimed_amount_cents: int
    received_at: str
    response_due_at: str
    status: str
    resolution_note: Optional[str]
    adjustment_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class CreditAssessment(TypedDict, total=False):
    id: str
    client_id: str
    assessed_at: str
    prior_posture: str
    new_posture: str
    trigger: str
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WageStatement(TypedDict, total=False):
    id: str
    client_id: str
    tax_year: int
    employee_ref: str
    wages_cents: int
    withheld_cents: int
    statement_kind: str
    corrects_statement_id: Optional[str]
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
