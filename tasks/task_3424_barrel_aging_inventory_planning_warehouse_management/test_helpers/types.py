"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity narratives (PRD §2.5, §3). Entities with full
system-managed metadata carry ``id``, ``created_at``, ``updated_at`` and
``version``; the two immutable record types (slot occupancies and barrel
assessments) carry only ``id`` and ``created_at`` (PRD §2.5).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    """The eight declared roles (PRD §2.1)."""

    DISTILLERY_PLANNER = "DistilleryPlanner"
    OPERATIONS_DIRECTOR = "OperationsDirector"
    WAREHOUSE_MANAGER = "WarehouseManager"
    MASTER_BLENDER = "MasterBlender"
    PROGRAM_DIRECTOR = "ProgramDirector"
    BONDED_PREPARER = "BondedPreparer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class ProjectState(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    COMMISSIONED = "COMMISSIONED"


class RickhousePosture(str, Enum):
    PLANNED = "PLANNED"
    OPERATING = "OPERATING"
    FULL = "FULL"


class WoodOrigin(str, Enum):
    AMERICAN_WHITE_OAK = "AMERICAN_WHITE_OAK"
    FRENCH_OAK = "FRENCH_OAK"
    MIZUNARA = "MIZUNARA"


class SpiritType(str, Enum):
    BOURBON = "BOURBON"
    RYE = "RYE"
    TENNESSEE = "TENNESSEE"
    SINGLE_MALT = "SINGLE_MALT"


class MaturationStatus(str, Enum):
    FILLED = "FILLED"
    AGING = "AGING"
    MATURE_ELIGIBLE = "MATURE_ELIGIBLE"
    DUMPED = "DUMPED"


class CustodyStatus(str, Enum):
    BONDED = "BONDED"
    WITHDRAWN = "WITHDRAWN"


class MoveReason(str, Enum):
    INITIAL_FILL = "INITIAL_FILL"
    ROTATION = "ROTATION"


class OccupancyStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AssessmentKind(str, Enum):
    EVAPORATION_READING = "EVAPORATION_READING"
    QUALITY_SAMPLE = "QUALITY_SAMPLE"


class LabelState(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"


class BlendBatchState(str, Enum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


class ProgramState(str, Enum):
    SELECTION = "SELECTION"
    LOCKED = "LOCKED"


class ReservationState(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class ReportState(str, Enum):
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    AMENDED = "AMENDED"


# --- Entity TypedDicts -------------------------------------------------------
# Lifecycle fields are present but null until the event that fills them
# (PRD §2.5), hence Optional[...] on required keys.


class CapacityExpansionProject(TypedDict):
    id: str
    name: str
    region_code: str
    floors: int
    rows_per_floor: int
    positions_per_row: int
    construction_lag_months: int
    planned_annual_distillation_liters: int
    state: str
    approved_at: Optional[str]
    commissioned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Rickhouse(TypedDict):
    id: str
    expansion_project_id: str
    name: str
    region_code: str
    floors: int
    rows_per_floor: int
    positions_per_row: int
    total_slots: int
    occupied_slots: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class WarehouseSlot(TypedDict):
    id: str
    rickhouse_id: str
    floor_index: int
    row_index: int
    position_index: int
    heat_factor: float
    created_at: str
    updated_at: str
    version: int


class Barrel(TypedDict):
    id: str
    wood_origin: str
    seasoning_months: int
    char_level: int
    spirit_type: str
    fill_proof: float
    fill_volume_liters: float
    min_maturation_months: int
    fill_date: str
    maturation_status: str
    custody_status: str
    current_volume_ledger_liters: float
    current_volume_statutory_liters: float
    current_slot_id: Optional[str]
    withdrawn_at: Optional[str]
    withdrawn_volume_liters: Optional[float]
    created_at: str
    updated_at: str
    version: int


class SlotOccupancy(TypedDict):
    """Immutable record (PRD §2.5): only id + created_at system metadata."""

    id: str
    created_at: str
    barrel_id: str
    slot_id: str
    move_reason: str
    start_at: str
    end_at: Optional[str]
    status: str


class BarrelAssessment(TypedDict):
    """Immutable record (PRD §2.5): only id + created_at system metadata."""

    id: str
    created_at: str
    barrel_id: str
    kind: str
    measured_volume_liters: Optional[float]
    sample_draw_liters: Optional[float]
    quality_score: Optional[int]
    assessed_at: str


class Label(TypedDict):
    id: str
    name: str
    age_statement_years: int
    spirit_type: str
    state: str
    created_at: str
    updated_at: str
    version: int


class BlendBatch(TypedDict):
    id: str
    label_id: str
    scheduled_bottling_date: str
    state: str
    validated_at: Optional[str]
    committed_at: Optional[str]
    final_blend_volume_liters: Optional[float]
    created_at: str
    updated_at: str
    version: int


class BlendComponent(TypedDict):
    id: str
    blend_batch_id: str
    barrel_id: str
    drawn_volume_liters: float
    created_at: str
    updated_at: str
    version: int


class PrivateSelectionProgram(TypedDict):
    id: str
    name: str
    spirit_type: str
    min_quality_score: int
    required_barrel_count: int
    reservation_window_days: int
    state: str
    available_slots: int
    created_at: str
    updated_at: str
    version: int


class BarrelReservation(TypedDict):
    id: str
    program_id: str
    barrel_id: str
    state: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class BondedPeriodReport(TypedDict):
    id: str
    period_start: str
    period_end: str
    opening_inventory_liters: Optional[float]
    period_fills_liters: Optional[float]
    period_withdrawals_liters: Optional[float]
    loss_actual_liters: Optional[float]
    loss_statutory_liters: Optional[float]
    reported_loss_liters: Optional[float]
    closing_inventory_liters: Optional[float]
    state: str
    prepared_by_user_id: Optional[str]
    filed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
