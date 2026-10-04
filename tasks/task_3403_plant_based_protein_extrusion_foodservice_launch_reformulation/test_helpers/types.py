"""Domain types: entity TypedDicts, status enums, role enum.

Field names and enum spellings follow PRD.md exactly. Every resource carries
the four common system-managed properties (id, created_at, updated_at,
version) from PRD section 2.5.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Enums -------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROCUREMENT_MANAGER = "ProcurementManager"
    QUALITY_MANAGER = "QualityManager"
    PLANT_MANAGER = "PlantManager"
    PRODUCT_MANAGER = "ProductManager"
    CHANNEL_MANAGER = "ChannelManager"
    DEMAND_PLANNER = "DemandPlanner"
    FINANCE_CONTROLLER = "FinanceController"


class IsolateType(str, Enum):
    PEA = "PEA"
    FABA_BEAN = "FABA_BEAN"
    SOY = "SOY"
    MUNG_BEAN = "MUNG_BEAN"


class SupplierQualificationStatus(str, Enum):
    PENDING_AUDIT = "PENDING_AUDIT"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"


class SupplierAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"


class SupplierDimension(str, Enum):
    QUALIFICATION = "QUALIFICATION"
    AGREEMENT = "AGREEMENT"


class LotQcStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class QcDecision(str, Enum):
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class SiteType(str, Enum):
    OWNED = "OWNED"
    CO_MAN = "CO_MAN"


class CertificationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class OperationalStatus(str, Enum):
    IDLE = "IDLE"
    SETUP = "SETUP"
    RUNNING = "RUNNING"
    CLEANING = "CLEANING"
    DOWN = "DOWN"


class ProductStatus(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    PILOT = "PILOT"
    ACTIVE = "ACTIVE"
    SUNSET = "SUNSET"
    DISCONTINUED = "DISCONTINUED"


class LabelStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class Claim(str, Enum):
    HIGH_PROTEIN = "HIGH_PROTEIN"
    LOW_SATURATED_FAT = "LOW_SATURATED_FAT"
    GLUTEN_FREE = "GLUTEN_FREE"
    NON_GMO = "NON_GMO"


class Channel(str, Enum):
    FOODSERVICE = "FOODSERVICE"
    RETAIL_REFRIGERATED = "RETAIL_REFRIGERATED"
    RETAIL_FROZEN = "RETAIL_FROZEN"
    SAMPLES = "SAMPLES"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"
    RECALLED = "RECALLED"
    ABORTED = "ABORTED"


class ProgramType(str, Enum):
    FOODSERVICE_LTO = "FOODSERVICE_LTO"
    SAMPLING_DEMO = "SAMPLING_DEMO"


class ProgramStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    IN_WINDOW = "IN_WINDOW"
    EVALUATING = "EVALUATING"
    CONVERTED = "CONVERTED"
    CONCLUDED = "CONCLUDED"
    TERMINATED = "TERMINATED"


class BatchDerivedStatus(str, Enum):
    WRITTEN_OFF = "WRITTEN_OFF"
    EXPIRED = "EXPIRED"
    DEPLETED = "DEPLETED"
    RESERVED = "RESERVED"
    AVAILABLE = "AVAILABLE"


class ForecastStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    LOCKED = "LOCKED"
    ACTUALIZED = "ACTUALIZED"


class WriteDownReason(str, Enum):
    FORECAST_MISS = "FORECAST_MISS"
    EXPIRY_RISK = "EXPIRY_RISK"
    RECALL = "RECALL"


class WriteDownStatus(str, Enum):
    PROPOSED = "PROPOSED"
    POSTED = "POSTED"
    REJECTED = "REJECTED"


class WriteDownDecision(str, Enum):
    POSTED = "POSTED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts (all carry id, created_at, updated_at, version) --------

class Supplier(TypedDict):
    id: str
    supplier_code: str
    isolate_type: str
    qualification_status: str
    audit_score: Optional[int]
    agreement_status: str
    agreement_start_date: str
    agreement_end_date: str
    committed_volume_kg: int
    delivered_volume_kg: int
    base_price_per_kg_cents: int
    price_floor_cents: int
    price_cap_cents: int
    open_lot_count: int
    created_at: str
    updated_at: str
    version: int


class IngredientLot(TypedDict):
    id: str
    supplier_id: str
    lot_code: str
    quantity_kg: int
    remaining_kg: int
    received_at: str
    market_index_pct: float
    moisture_pct: float
    protein_content_pct: float
    provisional_unit_cost_cents: int
    final_unit_cost_cents: Optional[int]
    qc_status: str
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict):
    id: str
    line_code: str
    site_type: str
    coman_partner_name: Optional[str]
    monthly_reserved_capacity_kg: Optional[int]
    hourly_capacity_kg: int
    supported_isolate_types: List[str]
    certification_status: str
    operational_status: str
    reserved_capacity_kg: int
    last_audit_texture_score: Optional[int]
    last_audit_moisture_variance_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    product_code: str
    generation_number: int
    supersedes_product_id: Optional[str]
    isolate_type: str
    status: str
    unit_cost_per_kg_cents: Optional[int]
    price_parity_index: Optional[float]
    parity_goal_met: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class LabelVersion(TypedDict):
    id: str
    product_id: str
    version_number: int
    protein_g: float
    fat_g: float
    sodium_mg: float
    claims: List[str]
    ingredient_statement: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    production_line_id: str
    product_id: str
    label_version_id: str
    program_id: Optional[str]
    is_dedicated: bool
    channel: str
    planned_quantity_kg: int
    scheduled_start: str
    scheduled_end: str
    status: str
    actual_quantity_kg: Optional[int]
    required_isolate_kg: Optional[int]
    consumed_lot_ids: List[str]
    cases_produced: Optional[int]
    unit_cost_cents_per_case: Optional[int]
    created_at: str
    updated_at: str
    version: int


class GrowthProgram(TypedDict):
    id: str
    program_code: str
    program_type: str
    partner_code: Optional[str]
    product_id: str
    window_start: str
    window_end: str
    committed_cases: Optional[int]
    dedicated_run_required: bool
    budget_cents: Optional[int]
    coupons_issued: Optional[int]
    coupons_redeemed: int
    delivered_cases: int
    attainment_pct: Optional[float]
    redemption_rate_pct: Optional[float]
    commitment_met: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FinishedGoodsBatch(TypedDict):
    id: str
    production_run_id: str
    product_id: str
    channel: str
    quantity_cases: int
    available_cases: int
    reserved_cases: int
    written_off_cases: int
    reserved_for_program_id: Optional[str]
    produced_at: str
    expiry_date: str
    unit_cost_cents_per_case: int
    recall_flag: bool
    derived_status: str
    created_at: str
    updated_at: str
    version: int


class DemandForecast(TypedDict):
    id: str
    product_id: str
    channel: str
    week_start: str
    forecast_cases: int
    actual_cases: Optional[int]
    variance_pct: Optional[float]
    is_miss: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryWriteDown(TypedDict):
    id: str
    finished_goods_batch_id: str
    demand_forecast_id: Optional[str]
    reason: str
    quantity_cases: int
    proposed_by_user_id: str
    decided_by_user_id: Optional[str]
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
