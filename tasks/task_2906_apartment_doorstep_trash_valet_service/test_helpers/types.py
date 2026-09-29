"""Domain types for the Apartment Doorstep Trash Valet Service API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them. Every persisted resource in this domain carries the same four
system-managed fields (`id`, `created_at`, `updated_at`, `version`) per PRD
2.4, so no TypedDict below omits them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROPERTY_MANAGER = "PropertyManager"
    VALET_OPS_MANAGER = "ValetOpsManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    VALET = "Valet"
    RESIDENT = "Resident"
    BILLING_ANALYST = "BillingAnalyst"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class PropertyStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ServiceContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ResidentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MOVED_OUT = "MOVED_OUT"


class CollectionsStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"


class OnboardingStatus(str, Enum):
    APPLIED = "APPLIED"
    BACKGROUND_PENDING = "BACKGROUND_PENDING"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    DEACTIVATED = "DEACTIVATED"


class Classification(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    CONTRACTOR_1099 = "CONTRACTOR_1099"
    EMPLOYEE_W2 = "EMPLOYEE_W2"


class ClassificationBasis(str, Enum):
    DECLARED = "DECLARED"
    OBSERVED = "OBSERVED"


class TaxFormType(str, Enum):
    W9 = "W9"
    W4 = "W4"


class VerificationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    ACCRUED = "ACCRUED"
    INVOICED = "INVOICED"
    CREDITED = "CREDITED"


class RescheduleAction(str, Enum):
    SKIP = "SKIP"
    SHIFT = "SHIFT"


class RouteAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"
    CANCELLED = "CANCELLED"


class ScanResult(str, Enum):
    SERVICED = "SERVICED"
    NO_SET_OUT = "NO_SET_OUT"
    TAGGED_NOT_SERVICED = "TAGGED_NOT_SERVICED"


class ContainerType(str, Enum):
    TRASH_BIN = "TRASH_BIN"
    RECYCLING_BIN = "RECYCLING_BIN"
    LOOSE_BAG = "LOOSE_BAG"


class NonComplianceType(str, Enum):
    EARLY_SET_OUT = "EARLY_SET_OUT"
    IMPROPER_CONTAINER = "IMPROPER_CONTAINER"
    RECYCLING_CONTAMINATION = "RECYCLING_CONTAMINATION"


class TagStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    FINED = "FINED"
    VOIDED = "VOIDED"


class FineStatus(str, Enum):
    ASSESSED = "ASSESSED"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"
    VOIDED = "VOIDED"


class FineOrigin(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class AdjudicationOutcome(str, Enum):
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"


class IncidentType(str, Enum):
    JAM = "JAM"
    OVERFLOW = "OVERFLOW"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"


class StatementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class Weekday(str, Enum):
    SUN = "SUN"
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"


class BackgroundCheckResult(str, Enum):
    CLEAR = "CLEAR"
    FAIL = "FAIL"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Property(TypedDict):
    id: str
    name: str
    unit_count: int
    market_code: str
    compactor_capacity_lbs: int
    status: str
    active_contract_id: Optional[str]
    escalation_level: int
    pending_fine_revenue_cents: int
    delinquent_resident_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    property_id: str
    per_unit_monthly_fee_cents: int
    property_revenue_share_bps: int
    service_night_days: List[str]
    effective_from: str
    effective_to: str
    sla_missed_threshold_bps: int
    status: str
    last_invoiced_period: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    property_id: str
    unit_number: int
    full_name: str
    move_in_date: str
    move_out_date: Optional[str]
    fee_passthrough_enabled: bool
    status: str
    collections_status: str
    fines_outstanding_cents: int
    fines_assessed_this_period_cents: int
    created_at: str
    updated_at: str
    version: int


class ValetContractor(TypedDict):
    id: str
    legal_name: str
    equipment_provided_by_company: bool
    sets_own_schedule: bool
    works_exclusively: bool
    weekly_committed_hours: int
    tax_form_type: Optional[str]
    direct_deposit_on_file: bool
    onboarding_status: str
    classification: str
    classification_basis: Optional[str]
    control_score: int
    observed_weekly_hours: float
    background_checked_by_user_id: Optional[str]
    created_by_user_id: str
    deactivation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceNight(TypedDict):
    id: str
    contract_id: str
    rescheduled_from_night_id: Optional[str]
    service_date: str
    service_window_start: str
    service_window_end: str
    seasonal_volume_index: int
    holiday_flag: bool
    verification_status: str
    billing_status: str
    expected_door_count: int
    scanned_door_count: int
    coverage_bps: int
    assigned_unit_coverage_count: int
    reschedule_action: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteAssignment(TypedDict):
    id: str
    service_night_id: str
    contractor_id: str
    unit_from: int
    unit_to: int
    unit_coverage_count: int
    status: str
    accepted_at: Optional[str]
    completed_at: Optional[str]
    scan_count: int
    abandon_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceScan(TypedDict):
    id: str
    route_assignment_id: str
    service_night_id: str
    resident_id: str
    scan_result: str
    container_type: str
    non_compliance_type: Optional[str]
    tag_status: str
    offense_ordinal: int
    scanned_at: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResidentFine(TypedDict):
    id: str
    scan_id: str
    resident_id: str
    tag_type: str
    offense_ordinal: int
    base_cents: int
    escalation_multiplier: float
    seasonal_uplift_applied: bool
    amount_cents: int
    uncapped_amount_cents: int
    origin: str
    status: str
    dispute_round: int
    assessed_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompactorIncident(TypedDict):
    id: str
    property_id: str
    incident_type: str
    description: Optional[str]
    reported_by_role: str
    reported_by_user_id: str
    reported_at: str
    ack_deadline_at: str
    status: str
    acknowledged_at: Optional[str]
    escalated_at: Optional[str]
    resolved_at: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonthlyStatement(TypedDict):
    id: str
    contract_id: str
    superseded_statement_id: Optional[str]
    billing_period: str
    variant: str
    gross_passthrough_cents: int
    scheduled_night_count: int
    missed_equivalent_nights: float
    missed_service_bps: int
    sla_credit_rate_bps: int
    missed_service_credit_cents: int
    property_revenue_share_cents: int
    net_due_from_property_cents: int
    status: str
    created_by_user_id: str
    issued_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
