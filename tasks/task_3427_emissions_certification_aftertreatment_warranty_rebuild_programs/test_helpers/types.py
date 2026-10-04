"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CERTIFICATION_ENGINEER = "CertificationEngineer"
    REGULATORY_OFFICER = "RegulatoryOfficer"
    FLEET_MANAGER = "FleetManager"
    SERVICE_ADVISOR = "ServiceAdvisor"
    WARRANTY_ADJUDICATOR = "WarrantyAdjudicator"
    REMAN_PLANNER = "RemanPlanner"


# ---------------------------------------------------------------------------
# Enumerations (PRD §3)
# ---------------------------------------------------------------------------
class RegulationStandardStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class Architecture(str, Enum):
    DOC_DPF_SCR = "DOC_DPF_SCR"
    DOC_DPF_SCR_ASC = "DOC_DPF_SCR_ASC"
    EGR_DOC_DPF_SCR = "EGR_DOC_DPF_SCR"


class CertificationStatus(str, Enum):
    DESIGN = "DESIGN"
    TESTING = "TESTING"
    UNDER_REVIEW = "UNDER_REVIEW"
    CERTIFIED = "CERTIFIED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"
    PHASED_OUT = "PHASED_OUT"


class InUseComplianceStatus(str, Enum):
    NOT_TESTED = "NOT_TESTED"
    CONFORMING = "CONFORMING"
    NON_CONFORMING = "NON_CONFORMING"


class SpecStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class CalibrationStatus(str, Enum):
    UNCALIBRATED = "UNCALIBRATED"
    CALIBRATED = "CALIBRATED"


class TestType(str, Enum):
    FTP = "FTP"
    RMC = "RMC"
    SET = "SET"
    NTE = "NTE"


class TestResult(str, Enum):
    UNRECORDED = "UNRECORDED"
    PASS = "PASS"
    FAIL = "FAIL"


class TestRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


class FleetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class UnitLifecycle(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class CampaignCompliance(str, Enum):
    CLEAR = "CLEAR"
    CAMPAIGN_OPEN = "CAMPAIGN_OPEN"
    REMEDIED = "REMEDIED"


class MaintenanceType(str, Enum):
    OIL_CHANGE = "OIL_CHANGE"
    DPF_CLEAN = "DPF_CLEAN"
    DEF_SERVICE = "DEF_SERVICE"
    VALVE_ADJUST = "VALVE_ADJUST"
    SENSOR_REPLACE = "SENSOR_REPLACE"


class FaultSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class AuthorizationTier(str, Enum):
    BASIC = "BASIC"
    CERTIFIED = "CERTIFIED"
    MASTER = "MASTER"


class AuthStatus(str, Enum):
    APPLIED = "APPLIED"
    AUDITED = "AUDITED"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class CertificationLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class CertStatus(str, Enum):
    CERT_ACTIVE = "CERT_ACTIVE"
    EXPIRED = "EXPIRED"


class ToolStatus(str, Enum):
    CALIBRATED_ACTIVE = "CALIBRATED_ACTIVE"
    RECAL_DUE = "RECAL_DUE"


class InUseOutcome(str, Enum):
    CONFORMING = "CONFORMING"
    NON_CONFORMING = "NON_CONFORMING"


class ComponentClass(str, Enum):
    AFTERTREATMENT_SCR = "AFTERTREATMENT_SCR"
    AFTERTREATMENT_DPF = "AFTERTREATMENT_DPF"
    DOSING_SYSTEM = "DOSING_SYSTEM"
    NOX_SENSOR = "NOX_SENSOR"
    EGR_SYSTEM = "EGR_SYSTEM"
    ENGINE_BASE = "ENGINE_BASE"


class CoverageVariant(str, Enum):
    EXTENDED_EMISSIONS = "EXTENDED_EMISSIONS"
    BASE_WARRANTY = "BASE_WARRANTY"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED_FULL = "APPROVED_FULL"
    APPROVED_PARTIAL = "APPROVED_PARTIAL"
    DENIED_NEGLECT = "DENIED_NEGLECT"
    PAID = "PAID"


class AdjudicateDecision(str, Enum):
    APPROVE_FULL = "APPROVE_FULL"
    APPROVE_PARTIAL = "APPROVE_PARTIAL"
    DENY_NEGLECT = "DENY_NEGLECT"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class CampaignType(str, Enum):
    RECALL = "RECALL"
    SERVICE_CAMPAIGN = "SERVICE_CAMPAIGN"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETION_REVIEW = "COMPLETION_REVIEW"
    CLOSED = "CLOSED"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_BAY = "IN_BAY"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class RemanScope(str, Enum):
    ENGINE = "ENGINE"
    COMPONENT = "COMPONENT"


class ComponentType(str, Enum):
    SCR_CATALYST = "SCR_CATALYST"
    DPF = "DPF"
    DOSER = "DOSER"
    TURBO = "TURBO"
    INJECTOR = "INJECTOR"


class SpecLevel(str, Enum):
    STANDARD = "STANDARD"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class CoreGrade(str, Enum):
    UNGRADED = "UNGRADED"
    A = "A"
    B = "B"
    C = "C"
    REJECT = "REJECT"


class RemanOrderStatus(str, Enum):
    QUOTED = "QUOTED"
    AWAITING_CORE = "AWAITING_CORE"
    CORE_RECEIVED = "CORE_RECEIVED"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    CLOSED = "CLOSED"
    CORE_REJECTED = "CORE_REJECTED"
    CORE_FORFEIT = "CORE_FORFEIT"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 common properties)
# ---------------------------------------------------------------------------
class RegulationStandard(TypedDict):
    id: str
    code: str
    nox_limit_g_per_bhp_hr: float
    pm_limit_g_per_bhp_hr: float
    useful_life_miles: int
    useful_life_hours: int
    useful_life_years: int
    base_warranty_years: int
    base_warranty_miles: int
    effective_model_year_first: int
    effective_model_year_last: int
    successor_standard_id: Optional[str]
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EngineFamily(TypedDict):
    id: str
    family_code: str
    model_year: int
    regulation_standard_id: str
    displacement_liters: float
    architecture: str
    certification_status: str
    production_entered: bool
    in_use_compliance_status: str
    submitted_by_user_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AftertreatmentSpec(TypedDict):
    id: str
    engine_family_id: str
    spec_version: int
    scr_catalyst_part: str
    dpf_part: str
    doser_part: str
    nox_sensor_count: int
    target_def_dosing_g_per_kwh: Optional[float]
    last_deviation_pct: Optional[float]
    calibration_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificationTestRun(TypedDict):
    id: str
    engine_family_id: str
    test_type: str
    lab_code: str
    scheduled_start: str
    scheduled_end: str
    measured_nox_g_per_bhp_hr: Optional[float]
    measured_pm_g_per_bhp_hr: Optional[float]
    deterioration_factor: float
    adjusted_nox_g_per_bhp_hr: Optional[float]
    adjusted_pm_g_per_bhp_hr: Optional[float]
    result: str
    status: str
    reviewed_by_user_id: Optional[str]
    invalidated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Fleet(TypedDict):
    id: str
    name: str
    fleet_code: str
    notification_contact: str
    status: str
    neglect_denial_count: int
    created_at: str
    updated_at: str
    version: int


class EngineUnit(TypedDict):
    id: str
    engine_family_id: str
    fleet_id: str
    serial_number: str
    model_year: int
    in_service_date: str
    accumulated_miles: int
    accumulated_hours: int
    lifecycle: str
    campaign_compliance: str
    predictive_service_due: bool
    last_snapshot_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FaultCode(TypedDict):
    code: str
    severity: str


# Append-only (PRD §2.5): id + created_at only — no updated_at, no version.
class MaintenanceRecord(TypedDict):
    id: str
    engine_unit_id: str
    performed_at: str
    maintenance_type: str
    odometer_at_service: int
    def_quality_ok: bool
    created_at: str


# Append-only (PRD §2.5): id + created_at only — no updated_at, no version.
class TelematicsSnapshot(TypedDict):
    id: str
    engine_unit_id: str
    recorded_at: str
    odometer_miles: int
    engine_hours: int
    fault_codes: List[FaultCode]
    def_consumption_gal: float
    nox_sensor_drift_ppm: float
    fault_risk_score: int
    created_at: str


class ServiceCenter(TypedDict):
    id: str
    name: str
    region: str
    authorization_tier: str
    auth_status: str
    bay_capacity_per_day: int
    core_credit_balance_cents: int
    core_reversal_count: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    service_center_id: str
    full_name: str
    badge_id: str
    certification_level: str
    emissions_endorsed: bool
    certified_at: str
    certification_expires_at: str
    cert_status: str
    created_at: str
    updated_at: str
    version: int


class DiagnosticTool(TypedDict):
    id: str
    service_center_id: str
    tool_serial: str
    software_version: str
    issued_at: str
    calibration_valid_until: str
    tool_status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.5): id + created_at only — no updated_at, no version.
class InUseComplianceResult(TypedDict):
    id: str
    engine_family_id: str
    test_period_label: str
    sample_size: int
    passing_units: int
    conformity_ratio: float
    outcome: str
    recorded_at: str
    created_at: str


class WarrantyClaim(TypedDict):
    id: str
    engine_unit_id: str
    service_center_id: str
    failed_component_class: str
    failure_code: str
    claimed_amount_cents: int
    submitted_by_role: str
    submitted_by_user_id: str
    coverage_variant: str
    neglect_score: Optional[int]
    approved_amount_cents: Optional[int]
    customer_share_cents: Optional[int]
    review_round: int
    status: str
    decided_by_user_id: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldCampaign(TypedDict):
    id: str
    engine_family_id: str
    campaign_code: str
    campaign_type: str
    defect_summary: str
    remedy_description: str
    remedy_bay_days: int
    completion_threshold: float
    notified_unit_count: int
    verified_unit_count: int
    completion_rate: float
    status: str
    announced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CampaignWorkOrder(TypedDict):
    id: str
    campaign_id: str
    engine_unit_id: str
    service_center_id: str
    assigned_technician_id: str
    scheduled_start_day: str
    bay_days: int
    status: str
    completed_at: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemanOrder(TypedDict):
    id: str
    engine_unit_id: str
    service_center_id: str
    reman_scope: str
    component_type: Optional[str]
    spec_level: str
    quoted_price_cents: int
    quoted_core_value_cents: int
    expected_core_return_by: str
    provisional_core_credit_cents: int
    core_grade: str
    final_core_credit_cents: Optional[int]
    spec_level_surcharge_cents: int
    invoice_total_cents: Optional[int]
    status: str
    core_returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageRead(TypedDict):
    base_covered: bool
    base_coverage_end: str
    extended_covered: bool
    extended_coverage_end: str
    extended_applies_to: str
