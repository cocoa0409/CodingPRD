"""Typed shapes and enumerations for the Retailer Installation Services API.

Field sets mirror the PRD exactly. `ServiceCategory`, `Jurisdiction`, `Installer`,
`InstallerCredential`, `Customer`, `Project`, `Measurement`, `ChangeOrder`,
`MaterialDelivery`, `InstallerAssignment`, `PunchListItem` and `WarrantyClaim`
carry `id`, `created_at`, `updated_at` and `version`; `ScorecardEvent` is an
immutable ledger row carrying only `id` and `created_at`.
"""

from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class Role:
    PROGRAM_ADMIN = "ProgramAdmin"
    NETWORK_MANAGER = "NetworkManager"
    PROJECT_COORDINATOR = "ProjectCoordinator"
    SERVICE_MANAGER = "ServiceManager"
    INSTALLER = "Installer"
    CUSTOMER = "Customer"


ALL_ROLES = [
    Role.PROGRAM_ADMIN,
    Role.NETWORK_MANAGER,
    Role.PROJECT_COORDINATOR,
    Role.SERVICE_MANAGER,
    Role.INSTALLER,
    Role.CUSTOMER,
]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class TradeCode:
    FLOORING = "FLOORING"
    GLAZING = "GLAZING"
    HVAC = "HVAC"
    ROOFING = "ROOFING"
    MILLWORK = "MILLWORK"


class UnitOfMeasure:
    SQFT = "SQFT"
    LINEAR_FT = "LINEAR_FT"
    EACH = "EACH"


class PermitPolicy:
    NEVER = "NEVER"
    ALWAYS = "ALWAYS"
    BY_JURISDICTION = "BY_JURISDICTION"


class CategoryStatus:
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class JurisdictionStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PermitResponsibleParty:
    RETAILER = "RETAILER"
    INSTALLER = "INSTALLER"
    CUSTOMER = "CUSTOMER"
    NOT_REQUIRED = "NOT_REQUIRED"


class InstallerStatus:
    APPLIED = "APPLIED"
    DOCS_PENDING = "DOCS_PENDING"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class BackgroundCheckResult:
    NONE = "NONE"
    PASS = "PASS"
    FAIL = "FAIL"


class CredentialStatus:
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class FulfillmentStatus:
    DRAFT = "DRAFT"
    MEASURE_PENDING = "MEASURE_PENDING"
    MEASURED = "MEASURED"
    CHANGE_PENDING = "CHANGE_PENDING"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    INSTALL_COMPLETE = "INSTALL_COMPLETE"
    PUNCH_OPEN = "PUNCH_OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FinancialStatus:
    QUOTED = "QUOTED"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    BALANCE_DUE = "BALANCE_DUE"
    SETTLED = "SETTLED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class PermitStatus:
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_APPLICATION = "PENDING_APPLICATION"
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED"
    INSPECTION_PASSED = "INSPECTION_PASSED"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    CLOSED = "CLOSED"


class MeasurementStatus:
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class SubfloorCondition:
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class ChangeOrderOrigin:
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    SITE_CONDITION = "SITE_CONDITION"
    MEASUREMENT_VARIANCE = "MEASUREMENT_VARIANCE"


class ChangeOrderStatus:
    DRAFT = "DRAFT"
    PENDING_CUSTOMER = "PENDING_CUSTOMER"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class UnitKind:
    PRIMARY_UNITS = "PRIMARY_UNITS"
    TRIM_LINEAR_FT = "TRIM_LINEAR_FT"
    FIXTURE_EACH = "FIXTURE_EACH"


class ChangeOrderDecision:
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    REQUEST_REVISION = "REQUEST_REVISION"


class DeliveryStatus:
    PLANNED = "PLANNED"
    IN_TRANSIT = "IN_TRANSIT"
    DELAYED = "DELAYED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class AssignmentStatus:
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"


class ReleaseReason:
    SCOPE_CHANGE_PENDING = "SCOPE_CHANGE_PENDING"
    INSTALLER_SUSPENDED = "INSTALLER_SUSPENDED"
    INSTALLER_REMOVED = "INSTALLER_REMOVED"
    PROJECT_CANCELLED = "PROJECT_CANCELLED"
    NO_SHOW = "NO_SHOW"


class QualityResult:
    NONE = "NONE"
    PASS = "PASS"
    PASS_WITH_PUNCH = "PASS_WITH_PUNCH"
    FAIL = "FAIL"


class DefectSeverity:
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SAFETY = "SAFETY"


class PunchItemStatus:
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    VERIFIED = "VERIFIED"


class ClaimType:
    LABOR_DEFECT = "LABOR_DEFECT"
    MATERIAL_DEFECT = "MATERIAL_DEFECT"


class WarrantyClaimStatus:
    SUBMITTED = "SUBMITTED"
    ESCALATED = "ESCALATED"
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class WarrantyDecision:
    UPHOLD = "UPHOLD"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


class ScorecardEventType:
    ON_TIME_COMPLETION = "ON_TIME_COMPLETION"
    LATE_COMPLETION = "LATE_COMPLETION"
    NO_SHOW = "NO_SHOW"
    PUNCH_MINOR = "PUNCH_MINOR"
    PUNCH_MAJOR = "PUNCH_MAJOR"
    PUNCH_SAFETY = "PUNCH_SAFETY"
    WARRANTY_UPHELD = "WARRANTY_UPHELD"
    CSAT_SURVEY = "CSAT_SURVEY"


class ScorecardEventSource:
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"


class WaiverTier:
    RETAILER_FAULT = "RETAILER_FAULT"
    COOLING_OFF = "COOLING_OFF"
    PERMIT_BLOCKED = "PERMIT_BLOCKED"
    GOODWILL = "GOODWILL"
    NONE = "NONE"


# --------------------------------------------------------------------------
# Resource shapes
# --------------------------------------------------------------------------
class ServiceCategory(TypedDict, total=False):
    id: str
    code: str
    name: str
    trade_code: str
    unit_of_measure: str
    base_labor_rate_cents_per_unit: int
    minimum_billable_units: float
    measurement_required: bool
    measurement_validity_days: int
    permit_policy: str
    deposit_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    name: str
    permit_required_trades: List[str]
    permit_unit_threshold: float
    permit_responsible_party: str
    inspection_required: bool
    inspection_lead_days: int
    max_concurrent_inspections: int
    background_check_recency_days: int
    min_liability_coverage_cents: int
    license_required: bool
    labor_complexity_multiplier: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Installer(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    primary_trade_code: str
    liability_coverage_cents: int
    insurance_expires_on: str
    status: str
    background_check_result: str
    background_check_completed_at: Optional[str]
    committed_minutes: int
    verified_credential_count: int
    rolling_event_count: int
    rolling_no_show_count: int
    completed_project_count: int
    quality_score: float
    timeliness_score: float
    satisfaction_score: float
    composite_score: float
    lifetime_composite_score: float
    removal_eligible: bool
    probation_started_at: Optional[str]
    removed_at: Optional[str]
    removal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstallerCredential(TypedDict, total=False):
    id: str
    installer_id: str
    jurisdiction_id: str
    trade_code: str
    license_number: str
    license_expires_on: str
    permit_pulling_authorized: bool
    verification_status: str
    verified_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    jurisdiction_id: str
    project_count: int
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    customer_id: str
    service_category_id: str
    jurisdiction_id: str
    site_address: str
    estimated_units: float
    effective_units: float
    requested_install_date: str
    quoted_labor_cents: int
    deposit_required_cents: int
    deposit_paid_cents: int
    deposit_held_cents: int
    deposit_applied_cents: int
    deposit_refunded_cents: int
    deposit_forfeited_cents: int
    final_labor_cents: Optional[int]
    change_order_upcharge_cents: int
    permit_fee_cents_billed: int
    total_due_cents: int
    balance_due_cents: int
    fulfillment_status: str
    financial_status: str
    permit_status: str
    permit_responsibility: str
    permit_application_reference: Optional[str]
    permit_issued_on: Optional[str]
    inspection_slot_start: Optional[str]
    inspection_slot_end: Optional[str]
    inspection_result: Optional[str]
    inspection_attempt_count: int
    quality_result: str
    workmanship_score: Optional[int]
    escalated_punch_count: int
    service_manager_review_required: bool
    install_completed_at: Optional[str]
    closed_at: Optional[str]
    cancelled_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Measurement(TypedDict, total=False):
    id: str
    project_id: str
    scheduled_at: str
    technician_name: str
    status: str
    completed_at: Optional[str]
    measured_units: Optional[float]
    subfloor_condition: Optional[str]
    obstruction_count: Optional[int]
    stair_flight_count: Optional[int]
    access_notes: Optional[str]
    variance_pct: Optional[float]
    change_order_triggered: bool
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrderLine(TypedDict, total=False):
    unit_kind: str
    units_delta: float


class ChangeOrder(TypedDict, total=False):
    id: str
    project_id: str
    origin: str
    lines: List[ChangeOrderLine]
    upcharge_cents: int
    net_primary_units_delta: float
    status: str
    revision_count: int
    revision_note: Optional[str]
    decided_at: Optional[str]
    source_measurement_id: Optional[str]
    supersedes_change_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialDelivery(TypedDict, total=False):
    id: str
    project_id: str
    promised_window_start: str
    promised_window_end: str
    sku_count: int
    material_cost_cents: int
    status: str
    actual_delivered_at: Optional[str]
    delay_days: int
    created_at: str
    updated_at: str
    version: int


class InstallerAssignment(TypedDict, total=False):
    id: str
    project_id: str
    installer_id: str
    window_start: str
    window_end: str
    duration_minutes: int
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    on_time: Optional[bool]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PunchListItem(TypedDict, total=False):
    id: str
    project_id: str
    severity: str
    description: str
    due_at: str
    status: str
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    verified_at: Optional[str]
    escalated_at: Optional[str]
    escalation_reason: Optional[str]
    escalated_to_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    project_id: str
    claim_type: str
    description: str
    status: str
    submitted_at: str
    triaged_at: Optional[str]
    decision_note: Optional[str]
    denial_reason: Optional[str]
    escalation_level: int
    escalated_to_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScorecardEvent(TypedDict, total=False):
    """Immutable ledger row: only `id` and `created_at` accompany the payload."""
    id: str
    installer_id: str
    project_id: Optional[str]
    event_type: str
    csat_score: Optional[int]
    quality_delta: float
    timeliness_delta: float
    satisfaction_delta: float
    occurred_at: str
    source: str
    created_at: str


class SettlementPreview(TypedDict, total=False):
    deposit_held_cents: int
    labor_forfeit_pct: float
    labor_forfeit_cents: int
    restocking_fee_cents: int
    gross_retained_cents: int
    matched_waiver_tier: str
    retained_cents: int
    refund_cents: int
    resulting_financial_status: str


class InstallerScorecard(TypedDict, total=False):
    rolling_quality_score: float
    rolling_timeliness_score: float
    rolling_satisfaction_score: float
    rolling_composite_score: float
    rolling_event_count: int
    rolling_no_show_count: int
    lifetime_quality_score: float
    lifetime_timeliness_score: float
    lifetime_satisfaction_score: float
    lifetime_composite_score: float
    lifetime_event_count: int
    removal_eligible: bool
    probation_active: bool


class ClockState(TypedDict, total=False):
    current_utc: str
    credentials_expired_count: int
    installers_suspended_count: int
    installers_rescored_count: int


JsonDict = Dict[str, Any]
