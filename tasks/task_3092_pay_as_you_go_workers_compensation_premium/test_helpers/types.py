"""Domain types: entity TypedDicts, status enums and the role enum.

Only the shape of the API surface is declared here; the behaviour lives in the PRD.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum ────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    UNDERWRITER = "Underwriter"
    EMPLOYER_ADMIN = "EmployerAdmin"
    PAYROLL_PROVIDER = "PayrollProvider"
    TAX_FILER = "TaxFiler"
    AUDITOR = "Auditor"


# ─── Status enums ─────────────────────────────────────

class EmployerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OtBasis(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class CoverageStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ReportingStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    GRACE = "GRACE"
    DELINQUENT = "DELINQUENT"
    NON_REPORTING = "NON_REPORTING"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    OVERDUE = "OVERDUE"
    SUSPENDED = "SUSPENDED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISPUTED = "DISPUTED"
    REASSIGNED = "REASSIGNED"


class ConnectionStatus(str, Enum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    BROKEN = "BROKEN"


class PayrollReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class InvoiceKind(str, Enum):
    PAYROLL = "PAYROLL"
    RETRO_ADJUSTMENT = "RETRO_ADJUSTMENT"
    AUDIT_TRUEUP = "AUDIT_TRUEUP"
    MINIMUM_PREMIUM = "MINIMUM_PREMIUM"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FILED = "FILED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    WAIVED = "WAIVED"


class FilingSource(str, Enum):
    SUI = "SUI"
    IRS_941 = "IRS_941"
    MANUAL = "MANUAL"


# ─── Entity TypedDicts ────────────────────────────────

class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    fein: str
    contact_email: str
    home_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassRate(TypedDict):
    class_code: str
    rate_per_100_cents: int


class StateRatingTable(TypedDict, total=False):
    id: str
    state_code: str
    effective_from: str
    effective_to: str
    monopolistic: bool
    per_capita_admin_fee_cents: int
    expense_constant_cents: int
    min_payroll_threshold_cents: int
    state_minimum_premium_cents: int
    ot_basis: str
    class_rates: List[ClassRate]
    max_payroll_per_executive_cents: int
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    employer_id: str
    policy_number: str
    effective_date: str
    expiry_date: str
    experience_mod: float
    coverage_status: str
    reporting_status: str
    billing_status: str
    last_report_received_at: Optional[str]
    consecutive_missed_cycles: int
    cumulative_billed_cents: int
    cumulative_collected_cents: int
    created_at: str
    updated_at: str
    version: int


class PolicyClassCode(TypedDict, total=False):
    id: str
    policy_id: str
    state_code: str
    class_code: str
    estimated_annual_payroll_cents: int
    effective_from: str
    assignment_status: str
    created_at: str
    updated_at: str
    version: int


class PayrollIntegration(TypedDict, total=False):
    id: str
    policy_id: str
    provider: str
    connection_status: str
    last_heartbeat_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollReport(TypedDict, total=False):
    id: str
    policy_id: str
    period_start: str
    period_end: str
    status: str
    failure_code: Optional[str]
    submitted_by: str
    idempotency_key: str
    created_at: str
    updated_at: str
    version: int


class PayrollLine(TypedDict, total=False):
    id: str
    payroll_report_id: str
    state_code: str
    class_code: str
    gross_wages_cents: int
    ot_premium_cents: int
    severance_cents: int
    executive_wages_cents: int
    headcount: int
    remuneration_basis_cents: int
    created_at: str
    updated_at: str
    version: int


class PremiumInvoice(TypedDict, total=False):
    id: str
    policy_id: str
    payroll_report_id: Optional[str]
    kind: str
    status: str
    manual_premium_cents: int
    experience_mod_applied: float
    premium_after_mod_cents: int
    per_capita_fees_cents: int
    expense_constant_cents: int
    total_cents: int
    due_date: str
    created_at: str
    updated_at: str
    version: int


class ClassCodeDispute(TypedDict, total=False):
    id: str
    policy_id: str
    policy_class_code_id: str
    requested_class_code: str
    effective_from: str
    supersedes_dispute_id: Optional[str]
    status: str
    resolution_reason: Optional[str]
    filed_by: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditReconciliation(TypedDict, total=False):
    id: str
    policy_id: str
    period_start: str
    period_end: str
    status: str
    filed_by: Optional[str]
    verified_by: Optional[str]
    reported_payroll_cents: int
    filing_payroll_cents: int
    variance_cents: int
    trueup_invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxFilingRecord(TypedDict, total=False):
    id: str
    policy_id: str
    state_code: str
    quarter: str
    period_start: str
    period_end: str
    reported_wages_cents: int
    source: str
    created_at: str
    updated_at: str
    version: int
