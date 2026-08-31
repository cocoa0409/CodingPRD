"""Domain types for the injection molding job shop API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every resource in this system carries ``id``, ``created_at``,
``updated_at`` and ``version`` -- the PRD states there is no entity here that
omits them.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------- roles ----

class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    SALES_ENGINEER = "SalesEngineer"
    PROCESS_ENGINEER = "ProcessEngineer"
    QUALITY_ENGINEER = "QualityEngineer"
    TOOLROOM_TECH = "ToolroomTech"
    CUSTOMER_REP = "CustomerRep"


# ------------------------------------------------------------- statuses ----

class PressStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFLINE = "OFFLINE"


class MoldStatus(str, Enum):
    """The tool's lifecycle axis."""
    NEW = "NEW"
    SAMPLING = "SAMPLING"
    PPAP_APPROVED = "PPAP_APPROVED"
    INTERIM_APPROVED = "INTERIM_APPROVED"
    QUARANTINED = "QUARANTINED"
    TRANSFERRED = "TRANSFERRED"
    RETIRED = "RETIRED"


class MoldServiceState(str, Enum):
    """The tool's maintenance axis, independent of its lifecycle axis."""
    SERVICEABLE = "SERVICEABLE"
    PM_DUE = "PM_DUE"
    IN_MAINTENANCE = "IN_MAINTENANCE"


class MoldOwnership(str, Enum):
    SHOP_OWNED = "SHOP_OWNED"
    CUSTOMER_OWNED = "CUSTOMER_OWNED"


class PressQualificationStatus(str, Enum):
    UNQUALIFIED = "UNQUALIFIED"
    RUN_AT_RATE_SCHEDULED = "RUN_AT_RATE_SCHEDULED"
    QUALIFIED = "QUALIFIED"
    FAILED = "FAILED"
    REVOKED = "REVOKED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class PPAPStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    INTERIM_APPROVED = "INTERIM_APPROVED"
    REJECTED = "REJECTED"


class ResinLotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    HOLD = "HOLD"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class JobRunStatus(str, Enum):
    """The production job's run axis."""
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    BLOCKED = "BLOCKED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class JobMaterialStatus(str, Enum):
    """The production job's material axis, independent of the run axis."""
    UNSTAGED = "UNSTAGED"
    STAGED = "STAGED"
    CONSUMED = "CONSUMED"


class JobBlockReason(str, Enum):
    MOLD_PM_DUE = "MOLD_PM_DUE"
    MOLD_QUARANTINED = "MOLD_QUARANTINED"
    INTERIM_PPAP_EXPIRED = "INTERIM_PPAP_EXPIRED"
    QUALIFICATION_REVOKED = "QUALIFICATION_REVOKED"


class MaintenanceOrderStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MaintenanceKind(str, Enum):
    PM = "PM"
    REPAIR = "REPAIR"


class ToolTransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"


class CapacityCommitStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ShortfallPolicy(str, Enum):
    STRICT = "STRICT"
    GOODWILL = "GOODWILL"


# -------------------------------------------------------------- entities ----

class Customer(TypedDict):
    id: str
    name: str
    code: str
    credit_hold: bool
    created_at: str
    updated_at: str
    version: int


class Press(TypedDict):
    id: str
    press_code: str
    tonnage: int
    shot_size_grams_max: int
    hourly_rate_cents: int
    status: str
    committed_minutes_scheduled: int
    created_at: str
    updated_at: str
    version: int


class Mold(TypedDict):
    id: str
    mold_code: str
    customer_id: str
    cavity_count: int
    shot_weight_grams: int
    required_min_tonnage: int
    required_max_tonnage: int
    pm_interval_shots: int
    tooling_cost_cents: int
    ownership: str
    status: str
    service_state: str
    total_shot_count: int
    shots_since_pm: int
    approved_max_regrind_bp: Optional[int]
    interim_expiry_shots: Optional[int]
    active_transfer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PressQualification(TypedDict):
    id: str
    mold_id: str
    press_id: str
    status: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    target_parts_per_hour: Optional[int]
    actual_parts_per_hour: Optional[int]
    attempt_count: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    customer_id: str
    mold_id: str
    part_weight_grams: int
    cycle_time_sec: int
    cavitation: int
    resin_grade: str
    resin_price_cents_per_kg: int
    annual_volume: int
    rate_press_id: Optional[str]
    margin_bp: Optional[int]
    quoted_lot_price_cents: Optional[int]
    quoted_piece_price_cents: Optional[int]
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PPAPSubmission(TypedDict):
    id: str
    mold_id: str
    quote_id: str
    level: int
    max_regrind_bp: int
    supersedes_submission_id: Optional[str]
    revision_no: int
    fai_dimensional_pass: Optional[bool]
    fai_sample_shots: Optional[int]
    submitted_by_user_id: Optional[str]
    internal_reviewed_by_user_id: Optional[str]
    customer_decided_by_user_id: Optional[str]
    interim_expiry_shots: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ResinLot(TypedDict):
    id: str
    resin_grade: str
    supplier_lot_code: str
    qty_kg_received: int
    moisture_bp: int
    qty_grams_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionJob(TypedDict):
    id: str
    quote_id: str
    mold_id: str
    press_id: str
    staged_resin_lot_id: Optional[str]
    planned_qty: int
    scheduled_start: str
    scheduled_end: str
    run_status: str
    material_status: str
    block_reason: Optional[str]
    total_shots: int
    parts_molded_total: int
    good_parts_total: int
    scrap_parts_total: int
    short_shot_shots_total: int
    total_run_minutes: int
    cumulative_regrind_bp: int
    first_pass_yield_bp: int
    actual_cycle_time_sec: Optional[int]
    job_direct_cost_cents: int
    job_overhead_cents: int
    job_total_cost_cents: int
    as_run_piece_price_cents: Optional[int]
    price_variance_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ProductionReport(TypedDict):
    id: str
    job_id: str
    resin_lot_id: Optional[str]
    shots: int
    short_shot_shots: int
    good_parts: int
    scrap_parts: int
    virgin_grams: int
    regrind_grams: int
    run_minutes: int
    instantaneous_regrind_bp: int
    report_direct_cost_cents: int
    is_reversed: bool
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceOrder(TypedDict):
    id: str
    mold_id: str
    kind: str
    window_start: str
    window_end: str
    status: str
    shots_at_open: int
    shots_reset: bool
    created_at: str
    updated_at: str
    version: int


class ToolTransfer(TypedDict):
    id: str
    mold_id: str
    to_customer_id: str
    from_ownership: str
    settlement_cents: int
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapacityCommit(TypedDict):
    id: str
    customer_id: str
    press_id: str
    window_start: str
    window_end: str
    committed_minutes: int
    shortfall_policy: str
    status: str
    consumed_minutes: int
    shortfall_minutes: int
    shortfall_fee_cents: int
    utilization_bp: int
    created_at: str
    updated_at: str
    version: int
