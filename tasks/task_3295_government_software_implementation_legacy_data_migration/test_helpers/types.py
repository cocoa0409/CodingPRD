"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROCUREMENT_OFFICER = "ProcurementOfficer"
    IMPLEMENTATION_MANAGER = "ImplementationManager"
    AGENCY_PROJECT_MANAGER = "AgencyProjectManager"
    VENDOR_PROJECT_MANAGER = "VendorProjectManager"
    FINANCE_OFFICER = "FinanceOfficer"
    BUSINESS_ANALYST = "BusinessAnalyst"
    DATA_MIGRATION_LEAD = "DataMigrationLead"
    INTERFACE_ENGINEER = "InterfaceEngineer"
    SUPPORT_MANAGER = "SupportManager"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    QA_OPEN = "Q&A_OPEN"
    QA_CLOSED = "Q&A_CLOSED"
    EVALUATION = "EVALUATION"
    AWARD_PENDING = "AWARD_PENDING"
    AWARDED = "AWARDED"
    IMPLEMENTATION = "IMPLEMENTATION"
    CLOSED = "CLOSED"
    PROTESTED = "PROTESTED"
    CANCELLED = "CANCELLED"


class PhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MilestoneStatus(str, Enum):
    PLANNED = "PLANNED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class BillingVariant(str, Enum):
    PAYMENT_ON_ACCEPTANCE = "PAYMENT_ON_ACCEPTANCE"
    RETAINAGE_HELD = "RETAINAGE_HELD"


class CriterionResult(str, Enum):
    PENDING = "PENDING"
    SATISFIED = "SATISFIED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class WorkflowProcessStatus(str, Enum):
    DRAFT = "DRAFT"
    MAPPED = "MAPPED"
    IN_REVIEW = "IN_REVIEW"
    REWORK = "REWORK"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class DecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RATIFIED = "RATIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class BatchStatus(str, Enum):
    DEFINED = "DEFINED"
    EXTRACTED = "EXTRACTED"
    CLEANSED = "CLEANSED"
    LOADED = "LOADED"
    RECONCILED = "RECONCILED"
    RECONCILE_FAILED = "RECONCILE_FAILED"
    ACCEPTED = "ACCEPTED"


class BatchDomain(str, Enum):
    ACCOUNTS_RECEIVABLE = "ACCOUNTS_RECEIVABLE"
    PROPERTY_TAX = "PROPERTY_TAX"
    COURT_CASES = "COURT_CASES"
    LICENSES = "LICENSES"
    PAYROLL = "PAYROLL"


class InterfaceStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_DEVELOPMENT = "IN_DEVELOPMENT"
    IN_TESTING = "IN_TESTING"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class CertificationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class UatCycleStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class UatSessionResult(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class TrainingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class EnrollmentOutcome(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    WITHDRAWN = "WITHDRAWN"


class GoLiveStatus(str, Enum):
    PROPOSED = "PROPOSED"
    READINESS_CHECKED = "READINESS_CHECKED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED = "CANCELLED"


class SupportTransitionStatus(str, Enum):
    WARRANTY = "WARRANTY"
    STABILIZATION = "STABILIZATION"
    STEADY_STATE = "STEADY_STATE"
    SUNSET = "SUNSET"


class TicketSeverity(str, Enum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"


class TicketResolution(str, Enum):
    RESOLVED = "RESOLVED"
    WORKAROUND = "WORKAROUND"
    DEFERRED = "DEFERRED"
    DUPLICATE = "DUPLICATE"


class MaintenanceStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    RENEWED = "RENEWED"


class StaffFunction(str, Enum):
    SUBJECT_MATTER_EXPERT = "SUBJECT_MATTER_EXPERT"
    UAT_TESTER = "UAT_TESTER"
    TRAINEE = "TRAINEE"
    PROJECT_SPONSOR = "PROJECT_SPONSOR"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class WindowKind(str, Enum):
    STATUTORY_DEADLINE = "STATUTORY_DEADLINE"
    ELECTION_FREEZE = "ELECTION_FREEZE"
    FISCAL_YEAR_END = "FISCAL_YEAR_END"
