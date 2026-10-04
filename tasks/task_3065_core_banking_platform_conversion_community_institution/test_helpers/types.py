"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class ProjectStatus(str, Enum):
    DISCOVERY = "DISCOVERY"
    CONFIGURATION = "CONFIGURATION"
    MOCK_CONVERSION = "MOCK_CONVERSION"
    CUTOVER_PLANNED = "CUTOVER_PLANNED"
    LIVE = "LIVE"
    CLOSED = "CLOSED"


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AccountStatus(str, Enum):
    STAGED = "STAGED"
    MAPPED = "MAPPED"
    EXCEPTION = "EXCEPTION"
    CLEARED = "CLEARED"
    CONVERTED = "CONVERTED"
    BLOCKED = "BLOCKED"


class MockRunState(str, Enum):
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    PASSED_WITH_EXCEPTIONS = "PASSED_WITH_EXCEPTIONS"
    PASSED = "PASSED"


class AncillaryStatus(str, Enum):
    PENDING = "PENDING"
    INTEGRATING = "INTEGRATING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    RETEST_PASSED = "RETEST_PASSED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentState(str, Enum):
    RESERVED = "RESERVED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class CommStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DefectStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    IN_FIX = "IN_FIX"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    GO = "GO"
    LIVE = "LIVE"
    ROLLED_BACK = "ROLLED_BACK"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    CONVERSION_ENGINEER = "ConversionEngineer"
    OPERATIONS_LEAD = "OperationsLead"
    TRAINER = "Trainer"
    COMMUNICATIONS_OFFICER = "CommunicationsOfficer"
    VENDOR_TRIAGE_LEAD = "VendorTriageLead"
    FINANCE_CONTROLLER = "FinanceController"


# --- Entities carrying id + created_at + updated_at + version ---

class ConversionProject(TypedDict, total=False):
    id: str
    institution_name: str
    incumbent_core_name: str
    target_core_name: str
    status: str
    mock_runs_used: int
    cutover_scheduled_date: Optional[str]
    cutoff_business_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductType(TypedDict, total=False):
    id: str
    project_id: str
    product_code: str
    kind: str
    accrual_method: str
    rate: float
    monthly_fee_cents: int
    fee_waiver_threshold_cents: Optional[int]
    minimum_balance_cents: int
    statement_frequency: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    project_id: str
    legacy_account_number: str
    new_account_number: str
    account_type: str
    product_type_id: str
    status: str
    exception_note: Optional[str]
    frozen_flag: bool
    opening_principal_cents: int
    conversion_balance_cents: int
    cutoff_accrued_interest_cents: int
    daily_interest_cents: int
    monthly_fee_assessed_cents: int
    statement_cycle_day: int
    accrual_start_date: str
    gl_account_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GLAccount(TypedDict, total=False):
    id: str
    project_id: str
    gl_code: str
    description: str
    expected_balance_cents: int
    converted_balance_cents: int
    variance_cents: int
    created_at: str
    updated_at: str
    version: int


class MockRun(TypedDict, total=False):
    id: str
    project_id: str
    run_label: str
    state: str
    started_at: str
    finished_at: Optional[str]
    duration_seconds: Optional[int]
    balanced_account_count: Optional[int]
    exception_account_count: Optional[int]
    converted_total_cents: Optional[int]
    outcome: Optional[str]
    is_cutover_baseline: bool
    created_at: str
    updated_at: str
    version: int


class AncillarySystem(TypedDict, total=False):
    id: str
    project_id: str
    name: str
    category: str
    status: str
    interface_version: str
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict, total=False):
    id: str
    project_id: str
    branch_name: str
    scheduled_start: str
    scheduled_end: str
    capacity: int
    reserved_count: int
    attended_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    project_id: str
    employee_code: str
    full_name: str
    branch_name: str
    role_scope: str
    parallel_ops_certified: bool
    created_at: str
    updated_at: str
    version: int


class CustomerComm(TypedDict, total=False):
    id: str
    project_id: str
    account_id: str
    comm_type: str
    wave: int
    send_after: str
    send_before: str
    scheduled_send_date: str
    resend_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Defect(TypedDict, total=False):
    id: str
    project_id: str
    title: str
    severity: str
    linked_system_id: Optional[str]
    reported_by: str
    status: str
    triage_priority: Optional[int]
    opened_at: str
    sla_deadline: str
    resolved_at: Optional[str]
    credit_eligible: bool
    reopened_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceCredit(TypedDict, total=False):
    id: str
    project_id: str
    month: str
    defect_ids: List[str]
    claim_status: str
    approved_by: Optional[str]
    breach_hours: List[int]
    credit_cents: int
    dispute_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Lighter-weight records: id + created_at only (no updated_at/version) ---

class Enrollment(TypedDict, total=False):
    id: str
    created_at: str
    parent_session_id: str
    employee_id: str
    state: str


class CutoverPlan(TypedDict, total=False):
    id: str
    created_at: str
    project_id: str
    planned_cutover_date: str
    file_freeze_start: str
    reopen_target: str
    go_no_go_checkpoint: str
    status: str


class CutoverTask(TypedDict, total=False):
    id: str
    created_at: str
    parent_plan_id: str
    task_name: str
    sequence: int
    conversion_window_start: str
    conversion_window_end: str
    depends_on_task_id: Optional[str]
    owner_role: str
    status: str
    duration_minutes: Optional[int]
