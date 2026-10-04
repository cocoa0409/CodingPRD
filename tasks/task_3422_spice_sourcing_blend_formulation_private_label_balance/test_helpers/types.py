"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SUPPLY_PLANNER = "SupplyPlanner"
    QUALITY_ANALYST = "QualityAnalyst"
    QUALITY_MANAGER = "QualityManager"
    FLAVOR_SCIENTIST = "FlavorScientist"
    PRODUCTION_SCHEDULER = "ProductionScheduler"
    RECALL_COORDINATOR = "RecallCoordinator"
    SUPPLIER_REP = "SupplierRep"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_TEST = "IN_TEST"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class TestType(str, Enum):
    MICRO = "MICRO"
    ADULTERANT_SCREEN = "ADULTERANT_SCREEN"
    PESTICIDE = "PESTICIDE"
    MOISTURE = "MOISTURE"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BrandType(str, Enum):
    BRANDED = "BRANDED"
    PRIVATE_LABEL = "PRIVATE_LABEL"


class SelectionPolicy(str, Enum):
    COST_MIN = "COST_MIN"
    FIFO_AGE = "FIFO_AGE"


class BlendRunStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    VOIDED = "VOIDED"


class SpecStatus(str, Enum):
    WITHIN_SPEC = "WITHIN_SPEC"
    OUT_OF_SPEC = "OUT_OF_SPEC"


class ProductionRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CommercialStatus(str, Enum):
    CREATED = "CREATED"
    SHIPPED = "SHIPPED"


class QualityStatus(str, Enum):
    CLEAR = "CLEAR"
    QUALITY_HOLD = "QUALITY_HOLD"
    RECALLED = "RECALLED"
    WITHDRAWN = "WITHDRAWN"


class HoldCause(str, Enum):
    NONE = "NONE"
    MANUAL = "MANUAL"
    LOT_QUARANTINE = "LOT_QUARANTINE"


class RecallTriggerType(str, Enum):
    LOT_SUSPECT = "LOT_SUSPECT"
    BATCH_SUSPECT = "BATCH_SUSPECT"
    REGULATORY = "REGULATORY"


class ScopePolicy(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class RecallSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_QUARANTINE = "AUTO_QUARANTINE"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    INITIATED = "INITIATED"
    CLOSED = "CLOSED"


class ConfidentialityLevel(str, Enum):
    STANDARD = "STANDARD"
    HIGH_SEGREGATION = "HIGH_SEGREGATION"


class KnowledgeTier(str, Enum):
    MASKED_ONLY = "MASKED_ONLY"
    FULL = "FULL"


# --- Entity TypedDicts ---
# All entities except SafetyTest carry the common shape (PRD §2.4):
# id, created_at, updated_at, version. SafetyTest is the append-only exception:
# only id and created_at (PRD §2.4).


class Supplier(TypedDict, total=False):
    id: str
    name: str
    origin_country: str
    certifications: List[str]
    knowledge_tier: str
    created_at: str
    updated_at: str
    version: int


class RawLot(TypedDict, total=False):
    id: str
    supplier_id: str
    spice_code: str
    origin_region: str
    crop_year: int
    quantity_kg: float
    quantity_remaining_kg: float
    quantity_consumed_kg: float
    quantity_wasted_kg: float
    flavor_intensity_units: float
    moisture_pct: float
    cost_per_kg_cents: int
    allergen_profile: str
    organic_certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyTest(TypedDict, total=False):
    # Append-only event: id + created_at only; NO updated_at, NO version (PRD §2.4)
    id: str
    lot_id: str
    test_type: str
    measured_value: float
    result: str
    lab_code: str
    analyst_user_id: str
    created_at: str


class BlendFormula(TypedDict, total=False):
    id: str
    product_code: str
    name: str
    brand_type: str
    target_flavor_units: float
    flavor_tolerance_pct: float
    max_moisture_pct: float
    status: str
    revision: int
    supersedes_formula_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FormulaLine(TypedDict, total=False):
    id: str
    formula_id: str
    masked_component_code: str
    spice_code: Optional[str]
    target_proportion_pct: Optional[float]
    allergen_profile: str
    organic_required: bool
    min_lot_flavor_units: float
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    lot_id: str
    spice_code: str
    allocated_kg: float
    line_cost_cents: int


class BlendRun(TypedDict, total=False):
    id: str
    formula_id: str
    selection_policy: str
    target_batch_kg: float
    status: str
    selected_allocations: Optional[List[Allocation]]
    residual_flavor_pct: Optional[float]
    blended_moisture_pct: Optional[float]
    cost_total_cents: Optional[int]
    spec_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict, total=False):
    id: str
    name: str
    capacity_kg_per_shift: int
    supported_changeover_classes: List[str]
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    line_id: str
    formula_id: str
    blend_run_id: str
    private_label_agreement_id: Optional[str]
    quantity_kg: float
    window_start: str
    window_end: str
    predecessor_run_id: Optional[str]
    changeover_class_required: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FinishedBatch(TypedDict, total=False):
    id: str
    production_run_id: str
    product_code: str
    brand_type: str
    quantity_kg: float
    produced_at: str
    shelf_life_days: int
    best_by_date: str
    genealogy_lot_ids: List[str]
    unit_cost_cents: int
    commercial_status: str
    quality_status: str
    quality_hold_cause: str
    quality_hold_lot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecallCase(TypedDict, total=False):
    id: str
    trigger_type: str
    suspect_lot_id: Optional[str]
    suspect_batch_id: Optional[str]
    scope_policy: str
    source: str
    affected_batch_ids: List[str]
    affected_quantity_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PrivateLabelAgreement(TypedDict, total=False):
    id: str
    retailer_name: str
    product_codes: List[str]
    confidentiality_level: str
    annual_commitment_kg: float
    development_nda_signed: bool
    produced_ytd_kg: float
    commitment_met: bool
    created_at: str
    updated_at: str
    version: int


class CapacityReservation(TypedDict, total=False):
    id: str
    line_id: str
    agreement_id: Optional[str]
    window_start: str
    window_end: str
    reserved_kg_per_week: int
    created_at: str
    updated_at: str
    version: int
