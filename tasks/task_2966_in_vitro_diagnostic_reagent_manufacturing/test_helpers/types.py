"""Domain types for the IVD Reagent Manufacturing API.

Entity TypedDicts, status enums and the role enum, derived from the PRD.

Two aggregates are immutable event records (PRD §2.4): a monitoring sample and a
test result carry **only** ``id`` and ``created_at`` — no ``updated_at`` and no
``version`` — so their TypedDicts deliberately omit those two keys.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1) — exactly six, spelled precisely
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    QC_ANALYST = "QCAnalyst"
    PRODUCTION_OPERATOR = "ProductionOperator"
    QA_RELEASER = "QAReleaser"
    REGULATORY_AFFAIRS = "RegulatoryAffairs"
    DISTRIBUTION_PLANNER = "DistributionPlanner"
    PLATFORM_ADMIN = "PlatformAdmin"


ALL_ROLES: List[str] = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class MaterialType(str, Enum):
    ANTIBODY = "ANTIBODY"
    ENZYME = "ENZYME"
    CALIBRATOR_MATERIAL = "CALIBRATOR_MATERIAL"
    BUFFER = "BUFFER"


class AcceptanceMode(str, Enum):
    ALL_PASS = "ALL_PASS"
    WEIGHTED_SCORE = "WEIGHTED_SCORE"


class MaterialTestCode(str, Enum):
    POTENCY = "POTENCY"
    PURITY = "PURITY"
    ENDOTOXIN = "ENDOTOXIN"
    IDENTITY = "IDENTITY"


class ReleaseTestCode(str, Enum):
    ACTIVITY = "ACTIVITY"
    CALIBRATION_SLOPE = "CALIBRATION_SLOPE"
    PRECISION = "PRECISION"
    LINEARITY = "LINEARITY"


class MaterialLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_TEST = "UNDER_TEST"
    OOS_INVESTIGATION = "OOS_INVESTIGATION"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"


class MaterialDisposition(str, Enum):
    QUALIFY = "QUALIFY"
    REJECT = "REJECT"
    INVESTIGATE = "INVESTIGATE"


class ClearanceStatus(str, Enum):
    DESIGN = "DESIGN"
    CLEARED = "CLEARED"
    WITHDRAWN = "WITHDRAWN"


class StorageCondition(str, Enum):
    TWO_TO_EIGHT_C = "TWO_TO_EIGHT_C"
    MINUS_TWENTY_C = "MINUS_TWENTY_C"


class RecordType(str, Enum):
    DESIGN_INPUT = "DESIGN_INPUT"
    DESIGN_OUTPUT = "DESIGN_OUTPUT"
    VERIFICATION = "VERIFICATION"
    VALIDATION = "VALIDATION"


class DesignRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class DispositionStatus(str, Enum):
    """Quality dimension of a finished lot (PRD §2.10)."""
    PLANNED = "PLANNED"
    IN_PROCESS = "IN_PROCESS"
    FILLED = "FILLED"
    UNDER_RELEASE_TEST = "UNDER_RELEASE_TEST"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"


class DistributionStatus(str, Enum):
    """Commercial-availability dimension of a finished lot (PRD §2.10)."""
    WITHHELD = "WITHHELD"
    AVAILABLE = "AVAILABLE"
    BLOCKED = "BLOCKED"


class ReagentLotDecision(str, Enum):
    RELEASE = "RELEASE"
    REJECT = "REJECT"


class ShelfLifeBasis(str, Enum):
    CLAIM = "CLAIM"
    REAL_TIME = "REAL_TIME"
    ACCELERATED = "ACCELERATED"


class ComponentRole(str, Enum):
    ANTIBODY = "ANTIBODY"
    ENZYME = "ENZYME"
    CALIBRATOR_MATERIAL = "CALIBRATOR_MATERIAL"
    BUFFER = "BUFFER"


class LotComponentStatus(str, Enum):
    CONSUMED = "CONSUMED"
    RETURNED = "RETURNED"


class FillRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class EnvironmentalState(str, Enum):
    CONFORMING = "CONFORMING"
    EXCURSION = "EXCURSION"
    DISQUALIFIED = "DISQUALIFIED"


class SampleType(str, Enum):
    VIABLE_AIR = "VIABLE_AIR"
    SURFACE = "SURFACE"
    NONVIABLE_PARTICLE = "NONVIABLE_PARTICLE"
    BIOBURDEN_BULK = "BIOBURDEN_BULK"


class ExcursionGrade(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class SubjectType(str, Enum):
    MATERIAL_LOT = "MATERIAL_LOT"
    REAGENT_LOT = "REAGENT_LOT"
    STABILITY_TIMEPOINT = "STABILITY_TIMEPOINT"


class TestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class StudyType(str, Enum):
    REAL_TIME = "REAL_TIME"
    ACCELERATED = "ACCELERATED"


class StabilityStudyStatus(str, Enum):
    PROTOCOL_DRAFT = "PROTOCOL_DRAFT"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    ABORTED = "ABORTED"


class ShelfLifeMethod(str, Enum):
    REAL_TIME_LAST_CONFORMING = "REAL_TIME_LAST_CONFORMING"
    ACCELERATED_Q10 = "ACCELERATED_Q10"


class BridgingStudyStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    FAILED = "FAILED"


class EquivalenceVerdict(str, Enum):
    PENDING = "PENDING"
    EQUIVALENT = "EQUIVALENT"
    NOT_EQUIVALENT = "NOT_EQUIVALENT"


class BridgingDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    MALFUNCTION_REPORTED = "MALFUNCTION_REPORTED"
    FIELD_ACTION_DECIDED = "FIELD_ACTION_DECIDED"
    CLOSED = "CLOSED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FieldAction(str, Enum):
    NONE = "NONE"
    ADVISORY = "ADVISORY"
    CORRECTION = "CORRECTION"
    REMOVAL = "REMOVAL"


class AllocationPolicy(str, Enum):
    FEFO_STRICT = "FEFO_STRICT"
    FEFO_WITH_SHORTFALL = "FEFO_WITH_SHORTFALL"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ALLOCATED = "ALLOCATED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    SHIPPED = "SHIPPED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    QUARANTINED = "QUARANTINED"


class ColdChainStatus(str, Enum):
    INTACT = "INTACT"
    EXCURSION_ACCEPTABLE = "EXCURSION_ACCEPTABLE"
    EXCURSION_REJECTED = "EXCURSION_REJECTED"


# ---------------------------------------------------------------------------
# Entity shapes — twelve aggregates carry id/created_at/updated_at/version,
# two event records carry only id/created_at (PRD §2.4).
# ---------------------------------------------------------------------------
class MaterialSpecification(TypedDict):
    id: str
    material_code: str
    material_type: str
    is_critical: bool
    potency_min_pct: float
    potency_max_pct: float
    endotoxin_max_eu_per_ml: float
    purity_min_pct: float
    required_test_codes: List[str]
    acceptance_mode: str
    max_retests: int
    retest_window_days: int
    created_at: str
    updated_at: str
    version: int


class MaterialLot(TypedDict):
    id: str
    material_specification_id: str
    vendor_lot_code: str
    received_quantity_units: float
    available_quantity_units: float
    consumed_quantity_units: float
    expiry_date: str
    qualification_status: str
    retest_count: int
    first_oos_at: Optional[str]
    acceptance_score: Optional[float]
    dispositioned_by_user_id: Optional[str]
    dispositioned_at: Optional[str]
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductSpecification(TypedDict):
    id: str
    product_code: str
    reference_material_code: str
    required_material_codes: List[str]
    release_test_codes: List[str]
    max_reference_bias_pct: float
    shelf_life_months_claim: int
    storage_condition: str
    min_shelf_life_days_at_ship: int
    clearance_status: str
    submission_ref: Optional[str]
    cleared_at: Optional[str]
    design_trace_complete: bool
    created_at: str
    updated_at: str
    version: int


class DesignControlRecord(TypedDict):
    id: str
    product_specification_id: str
    record_type: str
    document_ref: str
    traces_to_record_id: Optional[str]
    trace_depth: int
    status: str
    authored_by_user_id: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReagentLot(TypedDict):
    id: str
    product_specification_id: str
    lot_code: str
    planned_units: int
    filled_units: int
    available_units: int
    allocated_units: int
    shipped_units: int
    quarantined_units: int
    disposition_status: str
    distribution_status: str
    fill_completed_at: Optional[str]
    assigned_shelf_life_months: Optional[int]
    shelf_life_basis: Optional[str]
    shelf_life_basis_study_id: Optional[str]
    expiry_date: Optional[str]
    release_bias_max_pct: Optional[float]
    release_bias_sum_pct: Optional[float]
    em_excursion_count: int
    bioburden_cfu_per_ml: Optional[float]
    bridging_required: bool
    released_by_user_id: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotComponent(TypedDict):
    id: str
    reagent_lot_id: str
    material_lot_id: str
    component_role: str
    quantity_used: float
    status: str
    material_code_snapshot: str
    vendor_lot_code_snapshot: str
    created_at: str
    updated_at: str
    version: int


class FillRun(TypedDict):
    id: str
    reagent_lot_id: str
    line_code: str
    formulation_batch_code: str
    scheduled_start: str
    scheduled_end: str
    planned_fill_units: int
    filled_units: Optional[int]
    status: str
    started_at: Optional[str]
    ended_at: Optional[str]
    minor_excursion_count: int
    major_excursion_count: int
    bioburden_cfu_per_ml: Optional[float]
    environmental_state: str
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringSample(TypedDict):
    """Immutable event record — no updated_at, no version (PRD §2.4)."""
    id: str
    fill_run_id: str
    sample_type: str
    location_code: str
    result_value: float
    sampled_at: str
    limit_value: float
    excursion: bool
    excursion_grade: str
    created_at: str


class TestResult(TypedDict):
    """Immutable event record — no updated_at, no version (PRD §2.4)."""
    id: str
    subject_type: str
    material_lot_id: Optional[str]
    reagent_lot_id: Optional[str]
    stability_study_id: Optional[str]
    month_index: Optional[int]
    test_code: str
    measured_value: float
    reference_measured_value: Optional[float]
    is_retest: bool
    outcome: str
    bias_pct: Optional[float]
    recovery_pct: Optional[float]
    performed_by_user_id: str
    performed_at: str
    created_at: str


class StabilityStudy(TypedDict):
    id: str
    product_specification_id: str
    reagent_lot_id: str
    study_type: str
    chamber_code: str
    storage_temp_c: float
    protocol_start: str
    protocol_end: str
    planned_timepoints_months: List[int]
    baseline_value: float
    status: str
    timepoint_count: int
    last_conforming_month: Optional[int]
    established_shelf_life_months: Optional[int]
    shelf_life_method: Optional[str]
    protocol_approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BridgingStudy(TypedDict):
    id: str
    predicate_lot_id: str
    candidate_lot_id: str
    changed_material_lot_id: str
    paired_test_codes: List[str]
    status: str
    mean_bias_pct: Optional[float]
    max_bias_pct: Optional[float]
    equivalence_verdict: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    reagent_lot_id: str
    complaint_code: str
    narrative: str
    device_related_death_or_injury: bool
    received_at: str
    severity: Optional[str]
    malfunction_suspected: Optional[bool]
    reportable: Optional[bool]
    report_due_at: Optional[str]
    report_ref: Optional[str]
    reported_at: Optional[str]
    report_late: Optional[bool]
    field_action: Optional[str]
    field_action_decided_by_user_id: Optional[str]
    field_action_decided_at: Optional[str]
    triaged_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionOrder(TypedDict):
    id: str
    product_specification_id: str
    customer_code: str
    requested_units: int
    required_min_shelf_life_days: int
    ship_by: str
    allocation_policy: str
    allocated_units: int
    shortfall_units: int
    status: str
    planner_user_id: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    distribution_order_id: str
    reagent_lot_id: str
    allocated_units: int
    sequence_index: int
    status: str
    shipped_at: Optional[str]
    cumulative_excursion_minutes: float
    max_excursion_temp_c: Optional[float]
    cold_chain_status: str
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
