"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD's entity narratives.  MarketQuotation is the
append-only exception of PRD §2.5: it carries ``id`` and ``created_at`` only,
so its TypedDict omits ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCTION_PLANNER = "ProductionPlanner"
    COMPLEX_MANAGER = "ComplexManager"
    PLANT_MANAGER = "PlantManager"
    PROCUREMENT_LEAD = "ProcurementLead"
    HEALTH_OFFICIAL = "HealthOfficial"
    QUALITY_AUDITOR = "QualityAuditor"
    SALES_MANAGER = "SalesManager"
    CUSTOMER = "Customer"


class RegionCode(str, Enum):
    MIDWEST = "MIDWEST"
    SOUTHEAST = "SOUTHEAST"
    SOUTHWEST = "SOUTHWEST"
    WEST = "WEST"
    NORTHEAST = "NORTHEAST"


class HousingStyle(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    CAGE_FREE = "CAGE_FREE"
    ORGANIC = "ORGANIC"


class Program(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    CAGE_FREE = "CAGE_FREE"
    ORGANIC = "ORGANIC"


class Ownership(str, Enum):
    OWNED = "OWNED"
    CONTRACT = "CONTRACT"


class Pathogen(str, Enum):
    HPAI = "HPAI"
    LPAI = "LPAI"
    NEWCASTLE = "NEWCASTLE"
    SALMONELLA = "SALMONELLA"


class DisposalMethod(str, Enum):
    COMPOSTING = "COMPOSTING"
    BURIAL = "BURIAL"
    INCINERATION = "INCINERATION"
    LANDFILL = "LANDFILL"


class SizeClass(str, Enum):
    JUMBO = "JUMBO"
    EXTRA_LARGE = "EXTRA_LARGE"
    LARGE = "LARGE"
    MEDIUM = "MEDIUM"
    SMALL = "SMALL"
    PEEWEE = "PEEWEE"


class QuotationSource(str, Enum):
    URNER_BARRY = "URNER_BARRY"
    USDA_AMS = "USDA_AMS"


class Segment(str, Enum):
    RETAIL = "RETAIL"
    FOODSERVICE = "FOODSERVICE"
    PROCESSOR = "PROCESSOR"


class Commodity(str, Enum):
    CORN = "CORN"
    SOYBEAN_MEAL = "SOYBEAN_MEAL"


class BiosecurityPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    QUARANTINE = "QUARANTINE"


class FlockStatus(str, Enum):
    PLANNED = "PLANNED"
    GROWING = "GROWING"
    LAYING = "LAYING"
    MOLT = "MOLT"
    DEPLETED = "DEPLETED"
    DEPOPULATED = "DEPOPULATED"
    CANCELLED = "CANCELLED"


class CertificationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class DiseaseEventStatus(str, Enum):
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    CLEARED = "CLEARED"


class DepopulationOrderStatus(str, Enum):
    ISSUED = "ISSUED"
    COMPLETED = "COMPLETED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CommitmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    BOOKED = "BOOKED"
    ALLOCATED = "ALLOCATED"
    BLOCKED = "BLOCKED"
    SHIPPED = "SHIPPED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class FeedContractStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    FILLED = "FILLED"


class PackingRunStatus(str, Enum):
    PACKED = "PACKED"
    VERIFIED = "VERIFIED"


class CapitalProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_CONSTRUCTION = "IN_CONSTRUCTION"
    COMMISSIONED = "COMMISSIONED"


# --- Entity TypedDicts -------------------------------------------------------
# All primary resources carry id / created_at / updated_at / version (PRD
# §2.5).  MarketQuotation is the documented append-only exception.


class Complex(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    mill_receiving_tons_per_day: int
    biosecurity_posture: str
    corn_inventory_tons: int
    corn_organic_inventory_tons: int
    soy_inventory_tons: int
    soy_organic_inventory_tons: int
    ungraded_conventional_dozen: int
    ungraded_cage_free_dozen: int
    ungraded_organic_dozen: int
    ops_run_index: int
    last_ops_run_at: str
    created_at: str
    updated_at: str
    version: int


class House(TypedDict, total=False):
    id: str
    complex_id: str
    house_code: str
    housing_style: str
    capacity_hens: int
    hen_inventory: int
    downtime_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    house_id: str
    program: str
    auditor_name: str
    scheduled_date: str
    status: str
    result: Optional[str]
    valid_from: Optional[str]
    valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Flock(TypedDict, total=False):
    id: str
    house_id: str
    flock_code: str
    program: str
    ownership: str
    grower_name: Optional[str]
    placement_date: str
    placed_hen_count: int
    current_hen_count: int
    age_weeks: int
    molt_count: int
    molt_start_age_weeks: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DiseaseEvent(TypedDict, total=False):
    id: str
    complex_id: str
    pathogen: str
    detection_date: str
    scope_house_ids: list
    status: str
    confirmed_at: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DepopulationOrder(TypedDict, total=False):
    id: str
    disease_event_id: str
    house_id: str
    disposal_method: str
    downtime_days: int
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketQuotation(TypedDict, total=False):
    # Append-only (PRD §2.5): NO updated_at, NO version.
    id: str
    region_code: str
    size_class: str
    price_cents_per_dozen: int
    effective_date: str
    source: str
    created_at: str


class Customer(TypedDict, total=False):
    id: str
    name: str
    segment: str
    credit_limit_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerCommitment(TypedDict, total=False):
    id: str
    customer_id: str
    program: str
    region_code: str
    weekly_dozen_committed: int
    price_adjustment_cents_per_dozen: int
    effective_from: str
    effective_to: str
    cage_free_transition_deadline: Optional[str]
    required_cage_free_pct: float
    blocked_order_count: int
    required_conversion_hens: int
    achieved_conversion_hens: int
    transition_on_track: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    commitment_id: str
    ship_week_start: str
    dozen_ordered: int
    size_class: str
    status: str
    allocated_complex_id: Optional[str]
    allocated_dozen: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    sales_order_id: str
    ship_week_start: str
    dozen_shipped: int
    status: str
    provisional_index_cents: int
    provisional_unit_price_cents: int
    provisional_total_cents: int
    final_index_average_cents: Optional[int]
    final_volume_discount_cents: Optional[int]
    final_unit_price_cents: Optional[int]
    final_total_cents: Optional[int]
    quotation_ids_used: list
    disputed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeedContract(TypedDict, total=False):
    id: str
    complex_id: str
    commodity: str
    is_organic_certified: bool
    total_tons: int
    received_tons: int
    basis_cents_per_ton: int
    spot_reference_cents_per_ton: int
    hedged_tons: int
    hedge_futures_cents_per_ton: Optional[int]
    hedged_applied_tons: int
    total_cost_cents: int
    average_received_cost_cents_per_ton: Optional[int]
    delivery_start: str
    delivery_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FeedBatch(TypedDict, total=False):
    id: str
    complex_id: str
    program: str
    corn_tons: int
    soybean_tons: int
    tons_produced: int
    blended_cost_cents_per_ton: int
    actual_cost_per_dozen_cents: float
    standard_cost_per_dozen_cents: float
    created_at: str
    updated_at: str
    version: int


class PackingRun(TypedDict, total=False):
    id: str
    complex_id: str
    program: str
    dozen_input: int
    run_date: str
    cases_by_size: dict
    total_cases: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalProject(TypedDict, total=False):
    id: str
    commitment_id: str
    house_id: str
    investment_cents: int
    target_style: str
    construction_weeks: int
    construction_started_at: Optional[str]
    commissioned_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
