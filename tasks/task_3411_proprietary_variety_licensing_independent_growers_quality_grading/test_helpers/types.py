"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class BerryType(str, Enum):
    STRAWBERRY = "STRAWBERRY"
    RASPBERRY = "RASPBERRY"
    BLACKBERRY = "BLACKBERRY"
    BLUEBERRY = "BLUEBERRY"


class CulturalPractice(str, Enum):
    ORGANIC = "ORGANIC"
    CONVENTIONAL = "CONVENTIONAL"
    DRIP_IRRIGATION = "DRIP_IRRIGATION"
    INTEGRATED_PEST_MANAGEMENT = "INTEGRATED_PEST_MANAGEMENT"
    SOIL_FUMIGATION_FREE = "SOIL_FUMIGATION_FREE"


class VarietyStatus(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    RELEASED = "RELEASED"
    RECALLED = "RECALLED"


class GrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class AgreementStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PlantLotStatus(str, Enum):
    SHIPPED = "SHIPPED"
    PLANTED = "PLANTED"
    DEPLETED = "DEPLETED"
    RECALLED = "RECALLED"


class PlantingStatus(str, Enum):
    PLANNED = "PLANNED"
    PLANTED = "PLANTED"
    HARVESTING = "HARVESTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RECALLED = "RECALLED"


class LotStatus(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    GRADED = "GRADED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class GradeStatus(str, Enum):
    UNGRADED = "UNGRADED"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    DISPUTED = "DISPUTED"


class Grade(str, Enum):
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    PROCESS = "PROCESS"
    JUICE = "JUICE"
    REJECT = "REJECT"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    PAID = "PAID"


class StatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    FINAL = "FINAL"
    PAID = "PAID"


class RecallOrderStatus(str, Enum):
    ISSUED = "ISSUED"
    COMPLETE = "COMPLETE"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class Resolution(str, Enum):
    UPHOLD = "UPHOLD"
    ADJUST = "ADJUST"


class UserRole(str, Enum):
    PlatformAdmin = "PlatformAdmin"
    BreedingManager = "BreedingManager"
    ComplianceOfficer = "ComplianceOfficer"
    NurseryManager = "NurseryManager"
    GrowerPrincipal = "GrowerPrincipal"
    CoolingOperator = "CoolingOperator"
    QualityGrader = "QualityGrader"
    SettlementOfficer = "SettlementOfficer"


class Variety(TypedDict, total=False):
    id: str
    variety_code: str
    berry_type: str
    name: str
    status: str
    released_at: Optional[str]
    recalled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Grower(TypedDict, total=False):
    id: str
    legal_name: str
    region_code: str
    status: str
    suspended_at: Optional[str]
    exited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrowerAgreement(TypedDict, total=False):
    id: str
    grower_id: str
    variety_id: str
    region_code: str
    max_planting_units: int
    units_planted: int
    cultural_practice_codes: List[str]
    exclusive_marketing: bool
    effective_from: str
    effective_to: str
    status: str
    decided_at: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlantLot(TypedDict, total=False):
    id: str
    nursery_code: str
    agreement_id: str
    variety_id: str
    quantity_plants: int
    shipped_at: str
    season_year: int
    plants_reserved: int
    plants_planted: int
    plants_destroyed: int
    plants_available: int
    royalty_provisional_cents: int
    royalty_final_cents: Optional[int]
    royalty_adjustment_cents: Optional[int]
    depleted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Planting(TypedDict, total=False):
    id: str
    agreement_id: str
    plant_lot_id: str
    planned_plants: int
    plants_planted_actual: Optional[int]
    planted_on: Optional[str]
    region_code: str
    expected_first_harvest: Optional[str]
    expected_yield_kg: Optional[float]
    harvest_window_id: Optional[str]
    status: str
    completed_at: Optional[str]
    recalled_at: Optional[str]
    recall_compensation_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class HarvestWindow(TypedDict, total=False):
    id: str
    region_code: str
    variety_id: str
    week_start: str
    week_end: str
    target_volume_kg: int
    booked_volume_kg: float
    created_at: str
    updated_at: str
    version: int


class HarvestLot(TypedDict, total=False):
    id: str
    planting_id: str
    harvested_at: str
    gross_weight_kg: float
    tare_weight_kg: float
    net_kg: float
    received_at: Optional[str]
    pulp_temp_c_at_receipt: Optional[float]
    received_by_user_id: Optional[str]
    precool_hours: Optional[float]
    cold_chain_compliant: Optional[bool]
    lot_status: str
    grade_status: str
    flavor_brix: Optional[float]
    firmness_g: Optional[int]
    appearance_score: Optional[int]
    defect_pct: Optional[float]
    grade: Optional[str]
    pack_designation: Optional[str]
    submitted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    grade_submitted_at: Optional[str]
    grade_dispute_reason: Optional[str]
    grade_version: int
    pool_period_id: Optional[str]
    lot_gross_provisional_cents: Optional[int]
    lot_gross_final_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PoolPeriod(TypedDict, total=False):
    id: str
    berry_type: str
    week_start: str
    week_end: str
    is_shoulder_week: bool
    status: str
    estimated_price_cents_per_kg: Optional[int]
    actual_price_cents_per_kg: Optional[int]
    total_net_kg: Optional[float]
    total_weighted_kg: Optional[float]
    gross_pool_revenue_cents: Optional[int]
    marketing_fee_cents: Optional[int]
    net_pool_revenue_cents: Optional[int]
    pool_distributable_cents: Optional[int]
    provisional_pool_rate: Optional[float]
    final_pool_rate: Optional[float]
    closed_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict, total=False):
    id: str
    pool_period_id: str
    grower_id: str
    status: str
    provisional_net_cents: Optional[int]
    gross_cents: Optional[int]
    royalty_offset_cents: Optional[int]
    cold_chain_deduction_cents: Optional[int]
    recall_credit_cents: Optional[int]
    net_cents: Optional[int]
    issued_at: Optional[str]
    dispute_deadline: Optional[str]
    dispute_reason: Optional[str]
    dispute_count: int
    resolution: Optional[str]
    adjustment_total_cents: int
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecallOrder(TypedDict, total=False):
    id: str
    variety_id: str
    reason: str
    destroy_before: str
    compensation_per_plant_cents: int
    status: str
    plantings_recalled_count: int
    total_compensation_cents: int
    enforced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
