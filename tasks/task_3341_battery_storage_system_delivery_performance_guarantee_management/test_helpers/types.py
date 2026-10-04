"""Domain types: entity TypedDicts, status enums, role enum (PRD §3).

All entities in this API carry the four common system-managed properties
(``id``, ``created_at``, ``updated_at``, ``version``) per PRD §2.5.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROJECT_DEVELOPER = "ProjectDeveloper"
    PERFORMANCE_ENGINEER = "PerformanceEngineer"
    SERVICE_MANAGER = "ServiceManager"
    SERVICE_ENGINEER = "ServiceEngineer"
    WARRANTY_ADMIN = "WarrantyAdmin"
    SAFETY_AUTHORITY = "SafetyAuthority"
    MARKET_OPERATOR = "MarketOperator"


class MarketApplication(str, Enum):
    ENERGY_ARBITRAGE = "ENERGY_ARBITRAGE"
    FREQUENCY_REGULATION = "FREQUENCY_REGULATION"
    CAPACITY_FIRMING = "CAPACITY_FIRMING"


class DutyCycleProfile(str, Enum):
    ONE_CYCLE_DAILY = "ONE_CYCLE_DAILY"
    TWO_CYCLES_DAILY = "TWO_CYCLES_DAILY"
    CONTINUOUS = "CONTINUOUS"


class SizingStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"


class EsaStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class MilestoneKind(str, Enum):
    DELIVERY = "DELIVERY"
    COMMISSIONING = "COMMISSIONING"


class MilestoneStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACHIEVED = "ACHIEVED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class PermitType(str, Enum):
    THERMAL_RUNAWAY_PLAN = "THERMAL_RUNAWAY_PLAN"
    FIRE_CODE = "FIRE_CODE"
    LOCAL_APPROVAL = "LOCAL_APPROVAL"


class PermitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TestType(str, Enum):
    CAPACITY_TEST = "CAPACITY_TEST"
    RTE_TEST = "RTE_TEST"


class MeasurementBasis(str, Enum):
    NAMEPLATE = "NAMEPLATE"
    POI = "POI"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PerformanceTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AugmentationOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class AugmentationStatus(str, Enum):
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class LtsaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class SparePartOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    INSTALLED = "INSTALLED"
    CANCELLED = "CANCELLED"


class DefectType(str, Enum):
    CELL_DEFECT = "CELL_DEFECT"
    CAPACITY_SHORTFALL = "CAPACITY_SHORTFALL"
    RTE_SHORTFALL = "RTE_SHORTFALL"
    BMS_FAULT = "BMS_FAULT"


class CreditVariant(str, Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    OUTPUT_BASED = "OUTPUT_BASED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"


class BidMarket(str, Enum):
    DAY_AHEAD = "DAY_AHEAD"
    REAL_TIME = "REAL_TIME"


class BidSessionStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class Project(TypedDict, total=False):
    id: str
    name: str
    market_application: str
    duty_cycle_profile: str
    rated_power_mw: float
    rated_energy_mwh: float
    budget_cents: int
    duration_hours: float
    sizing_status: str
    commissioned_capacity_mwh: float
    equivalent_cycles: int
    projected_capacity_mwh: float
    augmentation_count: int
    created_at: str
    updated_at: str
    version: int


class EquipmentSupplyAgreement(TypedDict, total=False):
    id: str
    project_id: str
    contracted_power_mw: float
    contracted_energy_mwh: float
    guaranteed_capacity_mwh: float
    guaranteed_rte_pct: float
    price_per_mwh_cents: int
    total_price_cents: int
    ld_rate_per_day_cents: int
    ld_cap_cents: int
    accrued_ld_cents: int
    waived_ld_cents: int
    net_ld_due_cents: int
    guaranteed_delivery_date: str
    longstop_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryMilestone(TypedDict, total=False):
    id: str
    esa_id: str
    kind: str
    planned_date: str
    actual_date: Optional[str]
    days_late: int
    ld_applied_cents: int
    ld_waived_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyPermit(TypedDict, total=False):
    id: str
    project_id: str
    permit_type: str
    authority_reference: str
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceTest(TypedDict, total=False):
    id: str
    project_id: str
    test_type: str
    window_start: str
    window_end: str
    measurement_basis: str
    measured_capacity_mwh: Optional[float]
    aux_load_mwh: Optional[float]
    rte_intervals: Optional[list]
    evaluated_capacity_mwh: Optional[float]
    measured_rte_pct: Optional[float]
    result: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AugmentationEvent(TypedDict, total=False):
    id: str
    project_id: str
    planned_window_start: str
    planned_window_end: str
    added_capacity_mwh: float
    origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAgreement(TypedDict, total=False):
    id: str
    project_id: str
    annual_fee_cents: int
    covers_monitoring: bool
    covers_maintenance: bool
    covers_spare_parts: bool
    covers_software_updates: bool
    start_date: str
    end_date: str
    activated_at: Optional[str]
    credit_pool_cents: int
    credit_drawn_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SparePartOrder(TypedDict, total=False):
    id: str
    service_agreement_id: str
    warranty_claim_id: Optional[str]
    part_description: str
    part_cost_cents: int
    covered_by_credit: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    esa_id: str
    defect_type: str
    claimed_capacity_loss_mwh: float
    credit_variant: Optional[str]
    credit_amount_cents: Optional[int]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BidSession(TypedDict, total=False):
    id: str
    project_id: str
    market: str
    window_start: str
    window_end: str
    offer_mwh: float
    offer_price_cents_per_mwh: int
    clearing_price_cents_per_mwh: Optional[int]
    market_cleared_mwh: Optional[float]
    cleared_mwh: Optional[float]
    revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
