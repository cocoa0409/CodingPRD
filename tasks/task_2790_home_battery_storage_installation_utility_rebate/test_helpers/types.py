"""
Domain vocabulary: every enumeration and record shape the specification declares.

The string classes below exist so a test can say `BuildStatus.COMMISSIONED` instead
of spelling a literal, which makes a typo a NameError at collection time rather than
a mysterious assertion failure at run time. The TypedDicts document the field set of
each record; they are read as documentation by the tests and are never validated at
run time.
"""

from typing import Any, Dict, List, Optional, TypedDict


class UserRole:
    """The six role names accepted in the X-User-Role header."""

    CERTIFIED_INSTALLER = "CertifiedInstaller"
    HOMEOWNER = "Homeowner"
    AUTHORITY_HAVING_JURISDICTION = "AuthorityHavingJurisdiction"
    UTILITY_INTERCONNECTION_REVIEWER = "UtilityInterconnectionReviewer"
    REBATE_ADMINISTRATOR = "RebateAdministrator"
    MANUFACTURER_WARRANTY_AGENT = "ManufacturerWarrantyAgent"

    ALL = [
        CERTIFIED_INSTALLER,
        HOMEOWNER,
        AUTHORITY_HAVING_JURISDICTION,
        UTILITY_INTERCONNECTION_REVIEWER,
        REBATE_ADMINISTRATOR,
        MANUFACTURER_WARRANTY_AGENT,
    ]


# ── Installer account ────────────────────────────────
class CertificationLevel:
    NONE = "NONE"
    CERTIFIED = "CERTIFIED"
    ADVANCED = "ADVANCED"


class CertificationStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ── Site ─────────────────────────────────────────────
class TerritoryCode:
    TER_WEST = "TER_WEST"
    TER_EAST = "TER_EAST"
    TER_NORTH = "TER_NORTH"


# ── Load calculation ─────────────────────────────────
class LoadMethod:
    STANDARD = "NEC_220_82_STANDARD"
    MEASURED = "NEC_220_87_MEASURED"


class BackupScope:
    WHOLE_HOME = "WHOLE_HOME"
    ESSENTIAL_LOADS = "ESSENTIAL_LOADS"


class LoadCalcStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"


class LoadCalcDecision:
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"


# ── Battery system ───────────────────────────────────
class ModelCode:
    PWX_A = "PWX_A"
    PWX_B = "PWX_B"
    PWX_C = "PWX_C"


class InverterModel:
    GW2_HOME = "GW2_HOME"
    GW3_HOME = "GW3_HOME"


class BuildStatus:
    DESIGN_DRAFT = "DESIGN_DRAFT"
    DESIGN_LOCKED = "DESIGN_LOCKED"
    INSTALLED = "INSTALLED"
    COMMISSIONED = "COMMISSIONED"
    SUPERSEDED = "SUPERSEDED"
    DESIGN_HOLD = "DESIGN_HOLD"


class GridStatus:
    NOT_APPLIED = "NOT_APPLIED"
    APPLICATION_SUBMITTED = "APPLICATION_SUBMITTED"
    APPROVED_TO_INSTALL = "APPROVED_TO_INSTALL"
    PTO_GRANTED = "PTO_GRANTED"
    DENIED = "DENIED"


class WarrantyStatus:
    UNREGISTERED = "UNREGISTERED"
    ACTIVE = "ACTIVE"
    VOID = "VOID"


# ── Permit ───────────────────────────────────────────
class JurisdictionCode:
    AHJ_CITY = "AHJ_CITY"
    AHJ_COUNTY = "AHJ_COUNTY"


class PermitStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CORRECTIONS_REQUIRED = "CORRECTIONS_REQUIRED"
    ISSUED = "ISSUED"
    INSPECTION_PASSED = "INSPECTION_PASSED"
    INSPECTION_FAILED = "INSPECTION_FAILED"


class PermitDecision:
    ISSUE = "ISSUE"
    REQUEST_CORRECTIONS = "REQUEST_CORRECTIONS"


class InspectionResult:
    PASS = "PASS"
    FAIL = "FAIL"


# ── Interconnection application ──────────────────────
class ExportMode:
    NON_EXPORT = "NON_EXPORT"
    LIMITED_EXPORT = "LIMITED_EXPORT"
    FULL_EXPORT = "FULL_EXPORT"


class ApplicationStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUPPLEMENTAL_REVIEW = "SUPPLEMENTAL_REVIEW"
    APPROVED_TO_INSTALL = "APPROVED_TO_INSTALL"
    PTO_GRANTED = "PTO_GRANTED"
    DENIED = "DENIED"


class ApplicationDecision:
    APPROVE_TO_INSTALL = "APPROVE_TO_INSTALL"
    REQUEST_SUPPLEMENTAL = "REQUEST_SUPPLEMENTAL"
    DENY = "DENY"


# ── Incentive program and rebate claim ───────────────
class ProgramType:
    STATE_CAPACITY = "STATE_CAPACITY"
    UTILITY_UPFRONT = "UTILITY_UPFRONT"
    FEDERAL_ADDER = "FEDERAL_ADDER"


class ClaimStatus:
    RESERVED = "RESERVED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOID = "VOID"
    CLAWED_BACK = "CLAWED_BACK"


class ClaimDecision:
    APPROVE = "APPROVE"
    DENY = "DENY"


# ── Commissioning test ───────────────────────────────
class TestType:
    BACKUP_TRANSITION = "BACKUP_TRANSITION"
    CAPACITY_DISCHARGE = "CAPACITY_DISCHARGE"
    ANTI_ISLANDING = "ANTI_ISLANDING"
    FIRMWARE_BASELINE = "FIRMWARE_BASELINE"

    ALL = [BACKUP_TRANSITION, CAPACITY_DISCHARGE, ANTI_ISLANDING, FIRMWARE_BASELINE]


class TestStatus:
    SCHEDULED = "SCHEDULED"
    RECORDED = "RECORDED"
    CANCELLED = "CANCELLED"


class TestResult:
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


# ── Monitoring alert ─────────────────────────────────
class AlertCode:
    FIRMWARE_UPDATE_FAILED = "FIRMWARE_UPDATE_FAILED"
    CELL_IMBALANCE = "CELL_IMBALANCE"
    GATEWAY_OFFLINE = "GATEWAY_OFFLINE"
    THERMAL_DERATE = "THERMAL_DERATE"


class AlertSeverity:
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus:
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    CLAIM_APPROVED = "CLAIM_APPROVED"
    CLAIM_DENIED = "CLAIM_DENIED"


class AlertDecision:
    APPROVE = "APPROVE"
    DENY = "DENY"
    REQUEST_INFO = "REQUEST_INFO"


# ── BYOD enrollment, dispatch event and performance ──
class Season:
    SUMMER_2026 = "SUMMER_2026"
    WINTER_2026 = "WINTER_2026"


class EnrollmentStatus:
    PENDING_CONSENT = "PENDING_CONSENT"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class EventType:
    ECONOMIC = "ECONOMIC"
    EMERGENCY = "EMERGENCY"


class EventStatus:
    SCHEDULED = "SCHEDULED"
    SETTLED = "SETTLED"


class PerformanceStatus:
    PENDING = "PENDING"
    REPORTED = "REPORTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


# ── Record shapes ────────────────────────────────────
# Every record in this service carries the same four system-managed properties.


class CommonFields(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int


class InstallerAccount(CommonFields, total=False):
    company_name: str
    certification_level: str
    certification_status: str
    certified_model_codes: List[str]
    certification_expires_on: str
    clawback_count: int
    late_warranty_registration_count: int
    commissioned_system_count: int


class Site(CommonFields, total=False):
    homeowner_name: str
    utility_territory_code: str
    service_panel_amps: int
    floor_area_sqft: float
    postal_code: str
    existing_pv_kw_dc: float


class EssentialCircuit(TypedDict, total=False):
    label: str
    load_kw: float
    has_motor: bool


class LoadCalculation(CommonFields, total=False):
    site_id: str
    method: str
    backup_scope: str
    lighting_area_sqft: float
    appliance_load_va: float
    heating_va: float
    cooling_va: float
    measured_peak_kw: Optional[float]
    essential_circuits: List[EssentialCircuit]
    connected_load_kw: float
    required_continuous_kw: float
    required_surge_kw: float
    status: str
    revision_round_count: int
    reviewer_notes: Optional[str]


class BatterySystem(CommonFields, total=False):
    site_id: str
    installer_id: str
    load_calculation_id: str
    model_code: str
    unit_count: int
    inverter_model: str
    firmware_version: str
    installed_cost_cents: int
    usable_kwh: float
    continuous_kw: float
    build_status: str
    grid_status: str
    warranty_status: str
    verified_capacity_kwh: Optional[float]
    commissioned_at: Optional[str]
    warranty_deadline_at: Optional[str]
    warranty_registered_at: Optional[str]
    warranty_coverage_years: Optional[int]
    serial_numbers: Optional[List[str]]
    expands_system_id: Optional[str]


class Permit(CommonFields, total=False):
    battery_system_id: str
    jurisdiction_code: str
    plan_set_ref: str
    status: str
    correction_round_count: int
    issued_at: Optional[str]
    expires_on: Optional[str]
    inspection_findings: Optional[str]


class InterconnectionApplication(CommonFields, total=False):
    battery_system_id: str
    export_mode: str
    requested_export_kw: float
    approved_export_kw: Optional[float]
    status: str
    supplemental_round_count: int
    reviewed_by_user_id: Optional[str]
    pto_granted_by_user_id: Optional[str]
    pto_granted_at: Optional[str]


class IncentiveProgram(CommonFields, total=False):
    name: str
    program_type: str
    total_budget_cents: int
    remaining_budget_cents: int
    reserved_budget_cents: int
    paid_budget_cents: int
    tier1_limit_kwh: float
    tier1_rate_cents_per_kwh: int
    tier2_rate_cents_per_kwh: int
    per_project_cap_cents: int
    stack_priority: int
    max_stack_pct_of_cost_bp: int
    requires_export_commitment: bool
    min_capacity_commitment_kw: float


class RebateClaim(CommonFields, total=False):
    battery_system_id: str
    program_id: str
    capacity_commitment_kw: float
    export_commitment: str
    status: str
    basis_kwh_reserved: float
    basis_kwh_final: Optional[float]
    stack_ceiling_cents: int
    reserved_amount_cents: int
    final_amount_cents: Optional[int]
    approved_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    paid_at: Optional[str]
    clawback_reason: Optional[str]


class CommissioningTest(CommonFields, total=False):
    battery_system_id: str
    test_type: str
    window_start: str
    window_end: str
    status: str
    result: str
    recorded_at: Optional[str]
    transition_ms: Optional[int]
    delivered_kwh: Optional[float]
    anti_islanding_trip_ms: Optional[int]
    reported_firmware_version: Optional[str]


class MonitoringAlert(CommonFields, total=False):
    battery_system_id: str
    alert_code: str
    severity: str
    reported_firmware_version: Optional[str]
    status: str
    claim_round_count: int
    acknowledged_by_user_id: Optional[str]
    claimed_component: Optional[str]
    resolution_notes: Optional[str]


class ByodEnrollment(CommonFields, total=False):
    battery_system_id: str
    pledged_kw: float
    reserve_soc_pct: float
    season: str
    status: str
    cumulative_credited_kw: float
    cumulative_pledged_kw: float
    season_compliance_ratio: float
    settled_event_count: int
    performance_payment_cents_total: int
    consented_by_user_id: Optional[str]
    consented_at: Optional[str]


class DispatchEvent(CommonFields, total=False):
    territory_code: str
    window_start: str
    window_end: str
    event_type: str
    target_kw: float
    payment_rate_cents_per_kw: int
    status: str
    enrolled_pledged_kw: float
    total_net_payment_cents: int
    settled_at: Optional[str]


class DispatchPerformance(CommonFields, total=False):
    dispatch_event_id: str
    byod_enrollment_id: str
    pledged_kw_snapshot: float
    status: str
    delivered_kwh: Optional[float]
    avg_delivered_kw: Optional[float]
    credited_kw: Optional[float]
    performance_ratio: Optional[float]
    gross_payment_cents: Optional[int]
    shortfall_penalty_cents: Optional[int]
    bonus_cents: Optional[int]
    net_payment_cents: Optional[int]


Json = Dict[str, Any]
