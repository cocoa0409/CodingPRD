"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PLANT_MANAGER = "PlantManager"
    LINE_SCHEDULER = "LineScheduler"
    CUSTOMER_PLANNER = "CustomerPlanner"
    QUALITY_ENGINEER = "QualityEngineer"


class PlantPosture(str, Enum):
    OPEN = "OPEN"
    CONGESTED = "CONGESTED"
    LOCKDOWN = "LOCKDOWN"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEGOTIATING = "RENEGOTIATING"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class FreightZone(str, Enum):
    NEAR = "NEAR"
    MID = "MID"
    FAR = "FAR"


class VolumeTier(str, Enum):
    STANDARD = "STANDARD"
    REBATE = "REBATE"


class LineStatus(str, Enum):
    RUNNING = "RUNNING"
    QUALITY_HOLD = "QUALITY_HOLD"


class FormatShape(str, Enum):
    STANDARD = "STANDARD"
    SLEEK = "SLEEK"
    SLIM = "SLIM"
    STUBBY = "STUBBY"


class FormatStatus(str, Enum):
    PROPOSED = "PROPOSED"
    TOOLED = "TOOLED"
    QUALIFIED = "QUALIFIED"
    RETIRED = "RETIRED"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    HELD = "HELD"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class ForecastStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ScrapStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CREDITED = "CREDITED"
    EXPIRED = "EXPIRED"


class ScrapGrade(str, Enum):
    UBC = "UBC"
    PROCESS = "PROCESS"
    MIXED = "MIXED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DefectClass(str, Enum):
    SEAM_INTEGRITY = "SEAM_INTEGRITY"
    COATING = "COATING"
    FILLING_LINE_PERFORMANCE = "FILLING_LINE_PERFORMANCE"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class Plant(TypedDict, total=False):
    id: str
    name: str
    region: str
    warehouse_capacity_units: int
    warehouse_on_hand_units: int
    projected_warehouse_units: int
    posture: str
    ops_run_index: int
    scrap_credit_lbs_ytd: float
    metal_consumed_lbs_ytd: float
    recycled_content_pct: float
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    name: str
    home_region: str
    filling_lines_count: int
    created_at: str
    updated_at: str
    version: int


class SupplyAgreement(TypedDict, total=False):
    id: str
    plant_id: str
    customer_id: str
    freight_zone: str
    committed_annual_units: int
    pass_through_pct: float
    conversion_cost_cents_per_1000: float
    start_date: str
    end_date: str
    status: str
    ytd_settled_units: int
    delivered_revenue_cents: float
    volume_tier: str
    rolling_accuracy_pct: float
    lifetime_accuracy_pct: float
    created_at: str
    updated_at: str
    version: int


class MetalPriceIndex(TypedDict, total=False):
    # Immutable row: carries only id + created_at plus inputs (PRD §2.5).
    id: str
    period: str
    index_cents_per_lb: float
    created_at: str


class ProductionLine(TypedDict, total=False):
    id: str
    plant_id: str
    name: str
    nominal_speed_cans_per_hour: int
    base_spoilage_pct: float
    operational_status: str
    created_at: str
    updated_at: str
    version: int


class CanFormat(TypedDict, total=False):
    id: str
    plant_id: str
    customer_id: str
    size_code: str
    shape: str
    is_specialty: bool
    metal_lbs_per_1000_units: float
    tooling_investment_cents: int
    min_volume_commitment_units: int
    status: str
    delivered_units: int
    unamortized_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    agreement_id: str
    line_id: str
    format_id: str
    scheduled_qty: int
    graphics_code: str
    window_start: str
    window_end: str
    produced_qty: Optional[int]
    spoiled_qty: Optional[int]
    sheet_lbs_consumed: Optional[float]
    effective_spoilage_pct: Optional[float]
    spoilage_flag: bool
    provisional_unit_price_cents_per_1000: Optional[float]
    final_unit_price_cents_per_1000: Optional[float]
    settled_amount_cents: Optional[float]
    tier_delta_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerForecast(TypedDict, total=False):
    id: str
    agreement_id: str
    period: str
    forecast_qty: int
    actual_qty: Optional[int]
    accuracy_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScrapReturn(TypedDict, total=False):
    id: str
    customer_id: str
    plant_id: str
    pickup_window_start: str
    pickup_window_end: str
    declared_weight_lbs: float
    credited_weight_lbs: Optional[float]
    grade: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityIncident(TypedDict, total=False):
    id: str
    run_id: str
    line_id: str
    severity: str
    defect_class: str
    note: str
    status: str
    created_at: str
    updated_at: str
    version: int
