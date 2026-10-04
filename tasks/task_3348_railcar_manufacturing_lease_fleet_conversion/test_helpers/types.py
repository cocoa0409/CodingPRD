"""Domain types for the railcar manufacturing and lease fleet conversion API.

Status enums, the role enum and one TypedDict per persisted resource.

Every resource in this API carries the common field set — ``id``, ``created_at``,
``updated_at`` and ``version`` — because there is no resource in this catalogue
that omits ``updated_at`` or ``version``.  TypedDicts are declared ``total=False``
so that partial projections and write-response payloads type-check cleanly; the
API response itself is the source of truth at runtime.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum ────────────────────────────────────────

class UserRole(str, Enum):
    """The seven roles the platform recognizes, spelled exactly as declared."""

    PLATFORM_ADMIN = "PlatformAdmin"
    SUPPLY_CHAIN_COORDINATOR = "SupplyChainCoordinator"
    PRODUCTION_PLANNER = "ProductionPlanner"
    LEASE_ADMINISTRATOR = "LeaseAdministrator"
    PORTFOLIO_MANAGER = "PortfolioManager"
    REGULATORY_RETROFITIST = "RegulatoryRetrofitist"
    LESSEE = "Lessee"


# ─── Status / classification enums ────────────────────

class CarTypeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CarClass(str, Enum):
    BOXCAR = "BOXCAR"
    TANK = "TANK"
    HOPPER = "HOPPER"
    FLATCARS = "FLATCARS"
    GONDOLA = "GONDOLA"


class ComponentClass(str, Enum):
    WHEELSET = "WHEELSET"
    CASTING = "CASTING"
    COATING = "COATING"


class ProductionOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPONENT_RESERVED = "COMPONENT_RESERVED"
    RELEASED = "RELEASED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProductionOrderDisposition(str, Enum):
    SOLD = "SOLD"
    RETAINED = "RETAINED"


class SubstitutionEndorsementStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LeaseContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    AMENDMENT_DRAFTED = "AMENDMENT_DRAFTED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class LeaseType(str, Enum):
    FULL_SERVICE = "FULL_SERVICE"
    NET = "NET"


class LiabilityBearer(str, Enum):
    LESSOR = "LESSOR"
    LESSEE = "LESSEE"


class LesseeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CreditTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class LeaseFleetCarStatus(str, Enum):
    HELD = "HELD"
    ASSIGNED = "ASSIGNED"
    UNDER_REPAIR = "UNDER_REPAIR"
    SOLD = "SOLD"
    SCRAPPED = "SCRAPPED"


class CarAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REASSIGNED = "REASSIGNED"
    COMPLETED = "COMPLETED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"


class RetrofitProgramStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class RetrofitWorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ComponentPurchaseOrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class LeaseFleetSaleStatus(str, Enum):
    PENDING_SETTLEMENT = "PENDING_SETTLEMENT"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class PortfolioLedgerStatus(str, Enum):
    OPEN = "OPEN"


# ─── Entity TypedDicts (common fields on every resource) ───

class CarType(TypedDict, total=False):
    id: str
    model_code: str
    car_class: str
    build_hours: int
    regulatory_life_years: int
    line_count_family: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict, total=False):
    id: str
    part_number: str
    component_class: str
    unit_cost_cents: int
    lead_time_days: int
    on_hand_qty: int
    reserved_qty: int
    shortfall_qty: int
    created_at: str
    updated_at: str
    version: int


class CarTypeComponentRequirement(TypedDict, total=False):
    id: str
    car_type_id: str
    component_id: str
    qty_per_car: int
    created_at: str
    updated_at: str
    version: int


class ProductionOrder(TypedDict, total=False):
    id: str
    car_type_id: str
    quantity: int
    completed_qty: int
    unit_price_cents: int
    planned_shop_days: int
    disposition: str
    priority_rank: int
    order_date: str
    required_delivery_date: str
    status: str
    supersedes_production_order_id: Optional[str]
    retention_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstitutionEndorsement(TypedDict, total=False):
    id: str
    production_order_id: str
    original_component_id: str
    substitute_component_id: str
    substitute_qty_per_car: int
    status: str
    decides_material: bool
    created_at: str
    updated_at: str
    version: int


class LeaseContract(TypedDict, total=False):
    id: str
    lessee_id: str
    lease_type: str
    per_diem_rate_cents: int
    liability_bearer: str
    term_start_date: str
    term_end_date: str
    fleet_car_cap: int
    status: str
    amendment_seq: int
    capital_allocation_cents: int
    created_at: str
    updated_at: str
    version: int


class Lessee(TypedDict, total=False):
    id: str
    legal_name: str
    credit_tier: str
    utilization_threshold_pct: int
    credit_ceiling_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseFleetCar(TypedDict, total=False):
    id: str
    car_type_id: str
    production_order_id: Optional[str]
    lease_contract_id: Optional[str]
    acquisition_cost_cents: int
    accumulated_mileage: int
    status: str
    built_date: str
    regulatory_life_end_date: str
    retrofit_required: bool
    created_at: str
    updated_at: str
    version: int


class CarAssignment(TypedDict, total=False):
    id: str
    lease_fleet_car_id: str
    lease_contract_id: str
    lessee_id: str
    start_date: str
    end_date: str
    per_diem_rate_cents: int
    mileage_allowance: int
    mileage_used: int
    per_diem_accrued_cents: int
    mileage_charge_cents: int
    maintenance_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CarReturn(TypedDict, total=False):
    id: str
    lease_fleet_car_id: str
    car_assignment_id: str
    return_date: str
    mileage_since_last: int
    condition_grade: str
    maintenance_parts_cents: int
    mileage_overage_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class RetrofitProgram(TypedDict, total=False):
    id: str
    mandate_code: str
    description: str
    compliance_deadline_date: str
    required_shop_days_per_car: int
    required_component_id: Optional[str]
    program_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetrofitProgramCarType(TypedDict, total=False):
    id: str
    retrofit_program_id: str
    car_type_id: str
    created_at: str
    updated_at: str
    version: int


class RetrofitWorkOrder(TypedDict, total=False):
    id: str
    retrofit_program_id: str
    lease_fleet_car_id: str
    shop_line: str
    scheduled_start_date: str
    scheduled_end_date: str
    shop_days: int
    component_qty_consumed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComponentPurchaseOrder(TypedDict, total=False):
    id: str
    component_id: str
    qty_ordered: int
    unit_cost_cents: int
    order_date: str
    expected_receipt_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComponentReceipt(TypedDict, total=False):
    id: str
    component_purchase_order_id: str
    component_id: str
    qty_received: int
    receipt_date: str
    created_at: str
    updated_at: str
    version: int


class LeaseFleetSale(TypedDict, total=False):
    id: str
    lease_fleet_car_id: str
    lease_contract_id: Optional[str]
    lessee_id: Optional[str]
    buyer_name: str
    sale_price_cents: int
    net_book_value_cents: int
    writeback_liability_cents: int
    sale_date: str
    status: str
    gain_loss_cents: int
    created_at: str
    updated_at: str
    version: int


class PortfolioLedger(TypedDict, total=False):
    """Singleton ledger row — always present, always in status OPEN."""

    id: str
    status: str
    committed_capital_cents: int
    realized_gain_cents: int
    fleet_nbv_cents: int
    created_at: str
    updated_at: str
    version: int


# Convenience aliases used by assertions and fixtures.
EntityDict = dict
EntityList = List[dict]


__all__ = [
    # role enum
    "UserRole",
    # status and classification enums
    "CarTypeStatus", "CarClass", "ComponentClass", "ProductionOrderStatus",
    "ProductionOrderDisposition", "SubstitutionEndorsementStatus",
    "LeaseContractStatus", "LeaseType", "LiabilityBearer", "LesseeStatus",
    "CreditTier", "LeaseFleetCarStatus", "CarAssignmentStatus", "ConditionGrade",
    "SettlementStatus", "RetrofitProgramStatus", "RetrofitWorkOrderStatus",
    "ComponentPurchaseOrderStatus", "LeaseFleetSaleStatus", "PortfolioLedgerStatus",
    # entity TypedDicts
    "CarType", "Component", "CarTypeComponentRequirement", "ProductionOrder",
    "SubstitutionEndorsement", "LeaseContract", "Lessee", "LeaseFleetCar",
    "CarAssignment", "CarReturn", "RetrofitProgram", "RetrofitProgramCarType",
    "RetrofitWorkOrder", "ComponentPurchaseOrder", "ComponentReceipt",
    "LeaseFleetSale", "PortfolioLedger",
    # aliases
    "EntityDict", "EntityList",
]
