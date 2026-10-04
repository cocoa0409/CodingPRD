"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PLACEMENT_MANAGER = "PlacementManager"
    STORE_OPERATOR = "StoreOperator"
    SERVICE_DISPATCHER = "ServiceDispatcher"
    FIELD_TECHNICIAN = "FieldTechnician"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    PRODUCTION_PLANNER = "ProductionPlanner"


class AgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ChillerStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"
    NEEDS_REPAIR = "NEEDS_REPAIR"
    DECOMMISSIONED = "DECOMMISSIONED"


class ChillerModel(str, Enum):
    STANDARD = "STANDARD"
    COMPACT = "COMPACT"


class ModelVariant(str, Enum):
    DEMOGRAPHIC_LED = "DEMOGRAPHIC_LED"
    VELOCITY_LED = "VELOCITY_LED"


class EvaluationVerdict(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class PlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PerformanceStatus(str, Enum):
    PENDING = "PENDING"
    PERFORMING = "PERFORMING"
    UNDERPERFORMING = "UNDERPERFORMING"


class OperationalStatus(str, Enum):
    OK = "OK"
    SUSPENDED = "SUSPENDED"


class RetiredReason(str, Enum):
    UNDERPERFORMANCE_REMOVAL = "UNDERPERFORMANCE_REMOVAL"
    AGREEMENT_TERMINATION = "AGREEMENT_TERMINATION"
    RELOCATION = "RELOCATION"


class TicketOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_EXCURSION = "AUTO_EXCURSION"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    SPOILED = "SPOILED"


class LotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionStatus(str, Enum):
    SELLABLE = "SELLABLE"
    QUARANTINED = "QUARANTINED"
    REMOVED = "REMOVED"


class RemovalReason(str, Enum):
    NEAR_EXPIRY = "NEAR_EXPIRY"
    EXPIRED = "EXPIRED"
    COLD_CHAIN_BREACH = "COLD_CHAIN_BREACH"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    COMMISSIONED = "COMMISSIONED"


class CampaignStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


# --- Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version) ---

class Store(TypedDict):
    id: str
    name: str
    region: str
    demographic_index: int
    weekly_category_velocity_index: int
    competitor_density_index: int
    available_sqft: int
    distance_miles_from_plant: float
    created_at: str
    updated_at: str
    version: int


class SiteEvaluation(TypedDict):
    id: str
    store_id: str
    model_variant: str
    chiller_model: str
    forecast_weekly_units: float
    allocated_sqft: int
    footprint_score: float
    composite_score: float
    install_quote_cents: int
    payback_months: Optional[float]
    verdict: str
    created_at: str
    updated_at: str
    version: int


class PlacementAgreement(TypedDict):
    id: str
    store_id: str
    allocated_sqft: int
    max_capex_cents: int
    term_months: int
    status: str
    signed_at: Optional[str]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Chiller(TypedDict):
    id: str
    model: str
    serial_no: str
    capacity_units: int
    footprint_sqft: int
    status: str
    excursion_minutes_24h: int
    last_repair_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    store_id: str
    chiller_id: str
    agreement_id: str
    status: str
    performance_status: str
    operational_status: str
    underperforming_streak: int
    standing_deliveries_per_week: int
    safety_stock_units: int
    installed_quote_cents: int
    last_reported_weekly_units: Optional[int]
    payback_actuals_months: Optional[float]
    retired_reason: Optional[str]
    relocated_to_placement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TemperatureReading(TypedDict, total=False):
    # Append-only telemetry record: carries ONLY id + created_at of the common
    # fields (PRD §2.5) — no updated_at, no version.
    id: str
    chiller_id: str
    recorded_at: str
    temp_c: float
    duration_minutes: int
    is_excursion: bool
    created_at: str


class ServiceTicket(TypedDict):
    id: str
    chiller_id: str
    origin: str
    issue_summary: str
    status: str
    window_start: Optional[str]
    window_end: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    store_id: str
    lot_id: str
    quantity_units: int
    departed_at: str
    status: str
    delivered_at: Optional[str]
    accepted_units: Optional[int]
    rejected_units: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ProductLot(TypedDict):
    id: str
    sku: str
    produced_at: str
    quantity_units: int
    status: str
    expires_at: str
    unshipped_qty: int
    in_transit_qty: int
    in_store_qty: int
    removed_qty: int
    spoiled_qty: int
    conservation_invariant: str
    created_at: str
    updated_at: str
    version: int


class InventoryPosition(TypedDict):
    id: str
    store_id: str
    lot_id: str
    qty_on_hand: int
    expiry_date: str
    status: str
    removal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapacityProject(TypedDict):
    id: str
    name: str
    capacity_delta_units: int
    status: str
    sequence_no: Optional[int]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class TrialCampaign(TypedDict):
    id: str
    store_id: str
    name: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
