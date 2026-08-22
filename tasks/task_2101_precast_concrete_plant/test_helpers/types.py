"""Domain types for the precast concrete plant API: status enums and entity shapes."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    PRODUCTION_SUPERVISOR = "ProductionSupervisor"
    QC_TECHNICIAN = "QCTechnician"
    QUALITY_ENGINEER = "QualityEngineer"
    YARD_FOREMAN = "YardForeman"
    PERMIT_COORDINATOR = "PermitCoordinator"
    PROJECT_OWNER = "ProjectOwner"


# --------------------------------------------------------------------------
# Enumerated domain values
# --------------------------------------------------------------------------
class StrengthClass(str, Enum):
    C40 = "C40"
    C50 = "C50"
    C60 = "C60"
    C70 = "C70"


class MixDesignStatus(str, Enum):
    DRAFT = "DRAFT"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class BedType(str, Enum):
    LONG_LINE_PRESTRESS = "LONG_LINE_PRESTRESS"
    SELF_STRESSING_FORM = "SELF_STRESSING_FORM"
    FLAT_BED_RC = "FLAT_BED_RC"


class CastingBedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    DOWN = "DOWN"


class BedRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BLOCKED = "BLOCKED"
    TENSIONED = "TENSIONED"
    CURING = "CURING"
    RELEASE_READY = "RELEASE_READY"
    RELEASED = "RELEASED"
    STRIPPED = "STRIPPED"


class BlockedReason(str, Enum):
    MIX_SUSPENDED = "MIX_SUSPENDED"


class CuringCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class EnergySource(str, Enum):
    MODELED = "MODELED"
    METERED = "METERED"


class CylinderSetPurpose(str, Enum):
    RELEASE = "RELEASE"
    ACCEPTANCE_28DAY = "ACCEPTANCE_28DAY"
    INFORMATION = "INFORMATION"


class CylinderSetStatus(str, Enum):
    CAST = "CAST"
    TESTING = "TESTING"
    RELEASE_MET = "RELEASE_MET"
    RELEASE_NOT_MET = "RELEASE_NOT_MET"


class StrengthVariant(str, Enum):
    SET_AVERAGE = "SET_AVERAGE"
    TRIMMED_AVERAGE = "TRIMMED_AVERAGE"


class InclusionStatus(str, Enum):
    VALID = "VALID"
    DISCARDED_OUTLIER = "DISCARDED_OUTLIER"


class PieceProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    CAST = "CAST"
    STRIPPED = "STRIPPED"
    YARDED = "YARDED"
    LOADED = "LOADED"
    SHIPPED = "SHIPPED"
    ERECTED = "ERECTED"
    SCRAPPED = "SCRAPPED"


class PieceQcStatus(str, Enum):
    PENDING = "PENDING"
    HOLD = "HOLD"
    CLEARED = "CLEARED"
    NONCONFORMING = "NONCONFORMING"
    REPAIRED = "REPAIRED"
    REJECTED = "REJECTED"


class QcHoldReason(str, Enum):
    AWAITING_RELEASE_STRENGTH = "AWAITING_RELEASE_STRENGTH"
    MIX_SUSPENDED = "MIX_SUSPENDED"
    OPEN_NCR = "OPEN_NCR"


class YardSlotStatus(str, Enum):
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    FULL = "FULL"
    BLOCKED = "BLOCKED"


class YardPlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ReleaseReason(str, Enum):
    LOAD = "LOAD"
    SCRAP = "SCRAP"
    RESTACK = "RESTACK"


class HaulPermitStatus(str, Enum):
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class ShipmentStatus(str, Enum):
    BUILDING = "BUILDING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"


class DefectType(str, Enum):
    SPALL = "SPALL"
    HONEYCOMB = "HONEYCOMB"
    CRACK = "CRACK"
    DIMENSIONAL = "DIMENSIONAL"
    FINISH = "FINISH"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    STRUCTURAL = "STRUCTURAL"


class Disposition(str, Enum):
    PATCH_MINOR = "PATCH_MINOR"
    STRUCTURAL_REPAIR = "STRUCTURAL_REPAIR"
    USE_AS_IS = "USE_AS_IS"
    REJECT_RECAST = "REJECT_RECAST"


class RepairDispositionStatus(str, Enum):
    OPEN = "OPEN"
    DISPOSITIONED = "DISPOSITIONED"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    REINSPECTION = "REINSPECTION"
    CLOSED_ACCEPTED = "CLOSED_ACCEPTED"
    REJECTED_RECAST = "REJECTED_RECAST"
    SUPERSEDED = "SUPERSEDED"


class ReinspectResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# --------------------------------------------------------------------------
# Entity shapes.  Every resource except ShipmentLine carries id, created_at,
# updated_at and version; a shipment line carries only id and created_at.
# --------------------------------------------------------------------------
class Project(TypedDict):
    id: str
    name: str
    jobsite_city: str
    erection_start_date: str
    total_piece_count: int
    held_piece_count: int
    cleared_piece_count: int
    scrapped_piece_count: int
    erected_piece_count: int
    committed_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class MixDesign(TypedDict):
    id: str
    code: str
    strength_class: str
    design_28day_psi: int
    required_release_psi: int
    w_c_ratio: float
    cement_lb_per_cy: int
    unit_cost_cents_per_cy: int
    status: str
    suspension_reason: Optional[str]
    qualified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SteamZone(TypedDict):
    id: str
    zone_code: str
    boiler_capacity_bhp: float
    therm_rate_cents_per_therm: int
    created_at: str
    updated_at: str
    version: int


class CastingBed(TypedDict):
    id: str
    bed_code: str
    steam_zone_id: str
    bed_type: str
    length_ft: float
    max_strand_force_kips: float
    turnaround_buffer_hours: int
    status: str
    committed_strand_force_kips: float
    cumulative_cycle_count: int
    created_at: str
    updated_at: str
    version: int


class BedRun(TypedDict):
    id: str
    bed_id: str
    mix_design_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    blocked_reason: Optional[str]
    strand_count: Optional[int]
    strand_diameter_in: Optional[float]
    measured_elongation_in: Optional[float]
    theoretical_elongation_in: Optional[float]
    elongation_deviation_pct: Optional[float]
    computed_jacking_force_kips: Optional[float]
    piece_count: int
    cast_at: Optional[str]
    released_at: Optional[str]
    concrete_cost_cents: Optional[int]
    strand_cost_cents: Optional[int]
    energy_cost_cents: Optional[int]
    form_setup_cents: Optional[int]
    direct_subtotal_cents: Optional[int]
    overhead_rate_pct: Optional[float]
    overhead_cents: Optional[int]
    total_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CuringCycle(TypedDict):
    id: str
    bed_run_id: str
    steam_zone_id: str
    planned_start: str
    planned_end: str
    ramp_rate_f_per_hr: float
    soak_temp_f: float
    soak_hours: float
    steam_demand_bhp: float
    status: str
    metered_therms: Optional[float]
    modeled_therms: Optional[float]
    energy_therms: Optional[float]
    energy_source: Optional[str]
    energy_variance_pct: Optional[float]
    variance_flagged: bool
    energy_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CylinderSet(TypedDict):
    id: str
    bed_run_id: str
    purpose: str
    specimen_count: int
    cured_with_member: bool
    cast_at: str
    status: str
    recorded_break_count: int
    valid_break_count: int
    raw_mean_psi: Optional[float]
    qualified_strength_psi: Optional[int]
    strength_variant: Optional[str]
    recorded_by_user_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class CylinderBreak(TypedDict):
    id: str
    cylinder_set_id: str
    break_at: str
    age_hours: float
    load_lbf: float
    diameter_in: float
    computed_psi: int
    inclusion_status: str
    recorded_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Piece(TypedDict):
    id: str
    project_id: str
    mix_design_id: str
    bed_run_id: Optional[str]
    replaces_piece_id: Optional[str]
    piece_mark: str
    erection_sequence_no: int
    length_ft: float
    width_ft: float
    height_ft: float
    weight_lb: float
    concrete_volume_cy: float
    production_status: str
    qc_status: str
    qc_hold_reason: Optional[str]
    requires_haul_permit: bool
    allocated_cost_cents: Optional[int]
    repair_count: int
    created_at: str
    updated_at: str
    version: int


class YardSlot(TypedDict):
    id: str
    slot_code: str
    bay_code: str
    capacity_weight_lb: float
    max_stack_count: int
    status: str
    occupied_weight_lb: float
    stacked_count: int
    created_at: str
    updated_at: str
    version: int


class YardPlacement(TypedDict):
    id: str
    piece_id: str
    yard_slot_id: str
    stack_level: int
    placed_at: str
    released_at: Optional[str]
    release_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HaulPermit(TypedDict):
    id: str
    project_id: str
    permit_number: str
    issuing_state: str
    max_width_ft: float
    max_height_ft: float
    max_length_ft: float
    max_gross_weight_lb: float
    valid_from: str
    valid_to: str
    escort_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    project_id: str
    haul_permit_id: Optional[str]
    scheduled_departure: str
    status: str
    line_count: int
    gross_weight_lb: float
    max_width_ft: float
    max_height_ft: float
    max_length_ft: float
    is_oversize: bool
    permit_fee_cents: int
    dispatched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShipmentLine(TypedDict):
    """Written once and never modified: carries only id and created_at."""

    id: str
    shipment_id: str
    piece_id: str
    load_position: int
    line_surcharge_cents: int
    loaded_at: str
    created_at: str


class RepairDisposition(TypedDict):
    id: str
    piece_id: str
    defect_type: str
    severity: str
    description: str
    disposition: Optional[str]
    status: str
    reinspection_fail_count: int
    opened_by_user_id: str
    dispositioned_by_user_id: Optional[str]
    repaired_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
