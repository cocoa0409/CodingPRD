"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SITE_MANAGER = "SiteManager"
    PERMIT_COORDINATOR = "PermitCoordinator"
    JURISDICTION_REVIEWER = "JurisdictionReviewer"
    ENGINEER = "Engineer"
    PRINT_OPERATOR = "PrintOperator"
    QUALITY_INSPECTOR = "QualityInspector"
    TRADE_CONTRACTOR = "TradeContractor"


class JurisdictionStatus(str, Enum):
    ACTIVE = "ACTIVE"


class SiteStatus(str, Enum):
    REGISTERED = "REGISTERED"
    FOUNDATION_POURED = "FOUNDATION_POURED"
    FOUNDATION_CURED = "FOUNDATION_CURED"
    SITE_READY = "SITE_READY"
    ACTIVE_PRINT = "ACTIVE_PRINT"
    COMPLETED = "COMPLETED"
    SUSPENDED = "SUSPENDED"


class SitePosture(str, Enum):
    OPERATING = "OPERATING"
    PRECAUTIONARY = "PRECAUTIONARY"
    STOP = "STOP"


class DeploymentStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class LearningCurveVariant(str, Enum):
    FORWARD_LOOKING = "FORWARD_LOOKING"
    CHRONOLOGICAL = "CHRONOLOGICAL"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class PlanRevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class CodePath(str, Enum):
    PRESCRIPTIVE = "PRESCRIPTIVE"
    ALTERNATIVE_MEANS = "ALTERNATIVE_MEANS"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AM_REVIEW = "AM_REVIEW"
    RESUBMIT_REQUIRED = "RESUBMIT_REQUIRED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class PrinterSetupStatus(str, Enum):
    ASSEMBLED = "ASSEMBLED"
    LEVELED = "LEVELED"
    QUALIFIED = "QUALIFIED"
    DEMOBILIZED = "DEMOBILIZED"


class MixCode(str, Enum):
    LAVACRETE_A = "LAVACRETE_A"
    LAVACRETE_B = "LAVACRETE_B"
    LAVACRETE_C = "LAVACRETE_C"


class BatchStatus(str, Enum):
    PROPORTIONED = "PROPORTIONED"
    QUALIFIED = "QUALIFIED"
    EXHAUSTED = "EXHAUSTED"
    REJECTED = "REJECTED"


class PrintJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    READY_TO_PRINT = "READY_TO_PRINT"
    PRINTING = "PRINTING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    CANCELLED = "CANCELLED"


class InterruptionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    OVERRUN = "OVERRUN"


class InterruptionCause(str, Enum):
    WEATHER = "WEATHER"
    MATERIAL = "MATERIAL"
    MECHANICAL = "MECHANICAL"
    OPERATOR = "OPERATOR"
    INSPECTOR_HOLD = "INSPECTOR_HOLD"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    FAIL_BOND = "FAIL_BOND"
    FAIL_DIMENSIONAL = "FAIL_DIMENSIONAL"
    FAIL_BOTH = "FAIL_BOTH"


class InspectionDisposition(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    DEMOLISH_REQUIRED = "DEMOLISH_REQUIRED"


class TradeKind(str, Enum):
    ROOF = "ROOF"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    MECHANICAL = "MECHANICAL"


class TradeTaskStatus(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# Every entity carries the full common set (id, created_at, updated_at,
# version) per PRD §2.5; no entity opts out.


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    name: str
    permits_prescriptive_printed_path: bool
    alternative_means_review_days: int
    weather_station_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    address: str
    community_deployment_id: Optional[str]
    soil_class: str
    foundation_kind: str
    status: str
    foundation_poured_at: Optional[str]
    foundation_cured_at: Optional[str]
    posture: str
    created_at: str
    updated_at: str
    version: int


class CommunityDeployment(TypedDict, total=False):
    id: str
    name: str
    jurisdiction_id: str
    plan_id: str
    status: str
    planned_unit_count: int
    completed_unit_count: int
    learning_curve_baseline_minutes: Optional[int]
    learning_curve_factor: Optional[float]
    learning_curve_variant: str
    created_at: str
    updated_at: str
    version: int


class StructuralPlan(TypedDict, total=False):
    id: str
    title: str
    structural_system: str
    wall_thickness_mm: int
    wall_height_mm: int
    plan_area_m2: float
    current_revision_id: Optional[str]
    approved_revision_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanRevision(TypedDict, total=False):
    id: str
    plan_id: str
    supersedes_revision_id: Optional[str]
    revision_number: int
    engineering_notes: str
    required_code_path: str
    engineer_reviewer_id: Optional[str]
    approval_reviewer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict, total=False):
    id: str
    site_id: str
    plan_revision_id: str
    requested_path: str
    granted_path: Optional[str]
    review_round: int
    am_submitted_at: Optional[str]
    am_decision_due_at: Optional[str]
    fee_due_cents: int
    fee_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrinterSetup(TypedDict, total=False):
    id: str
    site_id: str
    gantry_model: str
    rail_span_mm: int
    leveling_tolerance_mm: float
    measured_level_deviation_mm: float
    is_within_tolerance: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MaterialBatch(TypedDict, total=False):
    id: str
    site_id: str
    mix_code: str
    water_cement_ratio: float
    target_slump_mm: int
    measured_slump_mm: int
    slump_within_band: bool
    pump_consistency_kg_per_min: float
    pump_window_kg_per_min: List[float]
    is_pumpable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherObservation(TypedDict, total=False):
    id: str
    site_id: str
    observed_at: str
    air_temp_c: float
    relative_humidity_pct: float
    wind_speed_mps: float
    precipitation_mm: float
    is_print_permissible: bool
    created_at: str
    updated_at: str
    version: int


class PrintJob(TypedDict, total=False):
    id: str
    site_id: str
    plan_revision_id: str
    printer_setup_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    actual_start_at: Optional[str]
    actual_end_at: Optional[str]
    total_layers_planned: int
    layers_printed: int
    cumulative_interruption_minutes: int
    continuous_run_minutes: Optional[int]
    max_permissible_interruption_minutes: Optional[int]
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PrintInterruption(TypedDict, total=False):
    id: str
    print_job_id: str
    cause: str
    paused_at: str
    resumed_at: Optional[str]
    duration_minutes: Optional[int]
    cure_penalty_layers: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class LayerInspection(TypedDict, total=False):
    id: str
    print_job_id: str
    layer_index_start: int
    layer_index_end: int
    bond_strength_mpa: float
    dimensional_deviation_mm: float
    passes_bond: bool
    passes_dimensional: bool
    outcome: str
    disposition: str
    supersedes_inspection_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConventionalTradeTask(TypedDict, total=False):
    id: str
    site_id: str
    trade: str
    sequence_rank: int
    earliest_start_at: str
    latest_end_at: str
    depends_on_print_job_id: str
    depends_on_trade_task_id: Optional[str]
    actual_start_at: Optional[str]
    actual_end_at: Optional[str]
    is_startable: bool
    start_blockers: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int
