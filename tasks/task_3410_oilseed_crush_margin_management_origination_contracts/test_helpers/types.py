"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD entity narratives (§2.4 common identity block, §3).
Resources with the full identity block carry id + created_at + updated_at +
version; the append-only MarketQuote (PRD §2.4: "a quote carries id and
created_at only; updated_at and version are absent") omits updated_at/version.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# =============================================================================
# Enums
# =============================================================================

class UserRole(str, Enum):
    """The ten declared roles (PRD §2.1)."""
    PLATFORM_ADMIN = "PlatformAdmin"
    ORIGINATION_MERCHANDISER = "OriginationMerchandiser"
    FARMER = "Farmer"
    CRUSH_TRADER = "CrushTrader"
    RISK_MANAGER = "RiskManager"
    PLANT_SCHEDULER = "PlantScheduler"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    PRODUCT_MERCHANDISER = "ProductMerchandiser"
    COMMERCIAL_BUYER = "CommercialBuyer"
    SUSTAINABILITY_AUDITOR = "SustainabilityAuditor"


class ContractType(str, Enum):
    CASH = "CASH"
    BASIS = "BASIS"
    DEFERRED = "DEFERRED"


class PricingStatus(str, Enum):
    UNPRICED = "UNPRICED"
    PARTIALLY_PRICED = "PARTIALLY_PRICED"
    PRICED = "PRICED"


class FulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    DELIVERING = "DELIVERING"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"


class ElectionOrigin(str, Enum):
    CLIENT = "CLIENT"
    FORCED = "FORCED"


class ScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class CertStandard(str, Enum):
    ISCC = "ISCC"
    REGEN = "REGEN"
    ORGANIC = "ORGANIC"


class Commodity(str, Enum):
    BEAN = "BEAN"
    OIL = "OIL"
    MEAL = "MEAL"


class PlantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"


class BuyerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TicketStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    DEPLETED = "DEPLETED"


class LaneMode(str, Enum):
    TRUCK = "TRUCK"
    RAIL = "RAIL"
    BARGE = "BARGE"


class ShipmentStatus(str, Enum):
    BOOKED = "BOOKED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CrushRunStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class BoardPositionStatus(str, Enum):
    ENTERED = "ENTERED"
    CONFIRMED = "CONFIRMED"
    OFFSET = "OFFSET"
    EXPIRED = "EXPIRED"


class Product(str, Enum):
    SOY_MEAL = "SOY_MEAL"
    SOY_OIL = "SOY_OIL"
    BIODIESEL_FEEDSTOCK = "BIODIESEL_FEEDSTOCK"


class SalesContractStatus(str, Enum):
    OPEN = "OPEN"
    DELIVERING = "DELIVERING"
    FULFILLED = "FULFILLED"
    DEFAULTED = "DEFAULTED"


class CarryDecision(str, Enum):
    CARRY = "CARRY"
    FLAT = "FLAT"


# =============================================================================
# Entity TypedDicts (full identity block: id, created_at, updated_at, version)
# =============================================================================

class Farmer(TypedDict, total=False):
    id: str
    legal_name: str
    county: str
    created_at: str
    updated_at: str
    version: int


class Elevator(TypedDict, total=False):
    id: str
    name: str
    region: str
    storage_capacity_bushels: float
    active_discount_schedule_id: str
    stored_bushels: float
    certified_stored_bushels: float
    receiving_open: bool
    created_at: str
    updated_at: str
    version: int


class QualityDiscountSchedule(TypedDict, total=False):
    id: str
    name: str
    moisture_base_pct: float
    moisture_shrink_pct_per_point: float
    moisture_discount_cents_per_point: int
    damage_free_pct: float
    damage_discount_cents_per_point: int
    fm_free_pct: float
    fm_discount_cents_per_point: int
    reject_moisture_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SustainabilityProgram(TypedDict, total=False):
    id: str
    name: str
    cert_standard: str
    premium_cents_per_bushel: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketQuote(TypedDict, total=False):
    """Append-only quote (PRD §2.4): id + created_at only — NO updated_at, NO version."""
    id: str
    created_at: str
    commodity: str
    quote_month: str
    price_cents: int
    quote_date: str


class CrushPlant(TypedDict, total=False):
    id: str
    name: str
    daily_crush_capacity_bushels: int
    daily_refinery_capacity_lbs: int
    biodiesel_feedstock_share_pct: float
    bean_inventory_bushels: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict, total=False):
    id: str
    company_name: str
    status: str
    open_claims_count: int
    created_at: str
    updated_at: str
    version: int


class PricingElection(TypedDict, total=False):
    bushels: float
    unit_price_cents: int
    elected_at: str
    origin: str


class OriginationContract(TypedDict, total=False):
    id: str
    farmer_id: str
    elevator_id: str
    program_id: Optional[str]
    contract_type: str
    quantity_bushels: float
    cash_price_cents_per_bushel: Optional[int]
    basis_cents_per_bushel: Optional[int]
    futures_month: Optional[str]
    pricing_deadline: Optional[str]
    storage_rate_cents_per_bushel_day: Optional[int]
    delivered_bushels: float
    priced_bushels: float
    priced_value_cents: int
    elections: List[Dict[str, Any]]
    accrued_storage_cents: int
    unpriced_pool_bushels: float
    last_accrual_date: Optional[str]
    estimated_settlement_cents: Optional[int]
    settlement_line_total_cents: Optional[int]
    settlement_accrual_deduction_cents: Optional[int]
    settlement_net_payable_cents: Optional[int]
    pricing_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryTicket(TypedDict, total=False):
    id: str
    contract_id: str
    elevator_id: str
    program_id: Optional[str]
    gross_bushels: float
    moisture_pct: float
    damage_pct: float
    foreign_material_pct: float
    schedule_id: Optional[str]
    shrink_bushels: Optional[float]
    net_bushels: Optional[float]
    discount_cents_per_bushel: Optional[int]
    premium_cents_per_bushel: Optional[int]
    applied_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StoragePosition(TypedDict, total=False):
    id: str
    elevator_id: str
    source_ticket_id: str
    program_id: Optional[str]
    bushels_initial: float
    current_bushels: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FreightLane(TypedDict, total=False):
    id: str
    origin_elevator_id: str
    destination_plant_id: str
    mode: str
    freight_cents_per_bushel: int
    transit_days: int
    daily_capacity_bushels: int
    created_at: str
    updated_at: str
    version: int


class ShipmentDraw(TypedDict, total=False):
    position_id: str
    bushels: float


class Shipment(TypedDict, total=False):
    id: str
    lane_id: str
    bushels: float
    departure_date: str
    certified_program_id: Optional[str]
    arrival_date: str
    freight_cost_cents: int
    draws: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class CrushRun(TypedDict, total=False):
    id: str
    plant_id: str
    run_date: str
    planned_bushels: int
    futures_month: str
    expected_oil_lbs: int
    expected_meal_lbs: int
    spread_cents_per_bushel: float
    planned_margin_cents: int
    realized_margin_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardCrushPosition(TypedDict, total=False):
    id: str
    futures_month: str
    bean_lots_long: int
    oil_lots_short: int
    meal_lots_short: int
    expiry_date: str
    locked_spread_cents_per_bushel: float
    locked_margin_cents: int
    realized_pnl_cents: Optional[int]
    entered_by_user_id: str
    confirmed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesDelivery(TypedDict, total=False):
    delivery_date: str
    quantity_lbs: int
    actual_protein_pct: Optional[float]
    actual_ffa_pct: Optional[float]
    recorded_at: str


class ProductSalesContract(TypedDict, total=False):
    id: str
    buyer_id: str
    plant_id: str
    product: str
    quantity_lbs: int
    price_cents_per_lb: int
    delivery_window_start: str
    delivery_window_end: str
    min_protein_pct: Optional[float]
    max_ffa_pct: Optional[float]
    delivered_lbs: int
    deliveries: List[Dict[str, Any]]
    claim_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarryAssessment(TypedDict, total=False):
    nearby_price_cents: int
    deferred_price_cents: int
    storage_cost_cents_per_bushel: int
    signal_cents_per_bushel: int
    decision: str


__all__ = [
    "UserRole",
    "ContractType",
    "PricingStatus",
    "FulfillmentStatus",
    "ElectionOrigin",
    "ScheduleStatus",
    "ProgramStatus",
    "CertStandard",
    "Commodity",
    "PlantStatus",
    "BuyerStatus",
    "TicketStatus",
    "PositionStatus",
    "LaneMode",
    "ShipmentStatus",
    "CrushRunStatus",
    "BoardPositionStatus",
    "Product",
    "SalesContractStatus",
    "CarryDecision",
    "Farmer",
    "Elevator",
    "QualityDiscountSchedule",
    "SustainabilityProgram",
    "MarketQuote",
    "CrushPlant",
    "Buyer",
    "PricingElection",
    "OriginationContract",
    "DeliveryTicket",
    "StoragePosition",
    "FreightLane",
    "ShipmentDraw",
    "Shipment",
    "CrushRun",
    "BoardCrushPosition",
    "SalesDelivery",
    "ProductSalesContract",
    "CarryAssessment",
]
