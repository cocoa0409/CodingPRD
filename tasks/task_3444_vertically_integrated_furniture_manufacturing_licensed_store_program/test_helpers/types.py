"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCTION_PLANNER = "ProductionPlanner"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    LICENSEE_MANAGER = "LicenseeManager"
    WHOLESALE_BUYER = "WholesaleBuyer"
    WARRANTY_ADMIN = "WarrantyAdmin"


class FactoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSTRAINED = "CONSTRAINED"
    OFFLINE = "OFFLINE"


class FactoryRegion(str, Enum):
    DOMESTIC = "DOMESTIC"
    OVERSEAS = "OVERSEAS"


class ComponentLine(str, Enum):
    FOAM = "FOAM"
    FRAMES = "FRAMES"
    UPHOLSTERY = "UPHOLSTERY"


class ProductLineLifecycle(str, Enum):
    CONCEPT = "CONCEPT"
    ACTIVE = "ACTIVE"
    CLEARANCE = "CLEARANCE"
    RETIRED = "RETIRED"


class ProductCategory(str, Enum):
    UPHOLSTERY = "UPHOLSTERY"
    CASEGOODS = "CASEGOODS"
    BEDDING = "BEDDING"


class LicenseeStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class TerritoryStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"


class PopulationTier(str, Enum):
    METRO = "METRO"
    SUBURBAN = "SUBURBAN"
    RURAL = "RURAL"


class RetailAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HOLD = "HOLD"
    CLOSED = "CLOSED"


class AllocationCycleStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    CLOSED = "CLOSED"


class BuyerType(str, Enum):
    LICENSEE = "LICENSEE"
    RETAIL_ACCOUNT = "RETAIL_ACCOUNT"


class DeliveryMode(str, Enum):
    FREIGHT_TO_STORE = "FREIGHT_TO_STORE"
    HOME_DELIVERY = "HOME_DELIVERY"


class AllocationState(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    RESERVED = "RESERVED"
    ALLOCATED = "ALLOCATED"
    WAITLISTED = "WAITLISTED"
    DROPPED = "DROPPED"


class FulfillmentState(str, Enum):
    PENDING = "PENDING"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DeliveryZone(str, Enum):
    LOCAL = "LOCAL"
    REGIONAL = "REGIONAL"
    EXTENDED = "EXTENDED"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class ClaimType(str, Enum):
    DEFECT = "DEFECT"
    DAMAGE_IN_TRANSIT = "DAMAGE_IN_TRANSIT"
    MISSING_PARTS = "MISSING_PARTS"


class ClaimStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    PARTS_ORDERED = "PARTS_ORDERED"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"


class ClaimDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PartsOrderStatus(str, Enum):
    QUEUED = "QUEUED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


# Every entity in this API carries the four common system-managed properties
# id / created_at / updated_at / version (PRD §2.4).

class Factory(TypedDict):
    id: str
    code: str
    region: str
    component_lines: List[str]
    weekly_capacity_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductLine(TypedDict):
    id: str
    name: str
    category: str
    style_code: str
    price_point_cents: int
    lifecycle: str
    clearance_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Licensee(TypedDict):
    id: str
    business_name: str
    royalty_rate: float
    merchandising_standard_version: str
    latest_audit_score: int
    status: str
    last_cycle_score: Optional[float]
    seasoned_score: Optional[float]
    royalty_accrued_cents: int
    chargeback_cents: int
    net_royalty_cents: int
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict):
    id: str
    region_code: str
    population_tier: str
    status: str
    assigned_licensee_id: Optional[str]
    assigned_at: Optional[str]
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailAccount(TypedDict):
    id: str
    business_name: str
    credit_limit_cents: int
    credit_used_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionCenter(TypedDict):
    id: str
    code: str
    supports_home_delivery: bool
    daily_crew_units: int
    region_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class AllocationCycle(TypedDict):
    id: str
    factory_id: str
    week_start: str
    capacity_units: int
    status: str
    licensee_reserved_units: int
    wholesale_reserved_units: int
    available_units: int
    run_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplyOrder(TypedDict):
    id: str
    buyer_type: str
    licensee_id: Optional[str]
    retail_account_id: Optional[str]
    allocation_cycle_id: str
    product_line_id: str
    quantity: int
    delivery_mode: str
    unit_price_cents: int
    provisional_total_cents: int
    final_total_cents: Optional[int]
    allocation_state: str
    fulfillment_state: str
    submitted_at: Optional[str]
    delivered_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryAppointment(TypedDict):
    id: str
    supply_order_id: str
    licensee_id: str
    dc_id: str
    zone: str
    region_code: str
    window_start: str
    window_end: str
    crew_units: int
    stairs_flights: int
    status: str
    estimate_fee_cents: int
    final_fee_cents: Optional[int]
    actual_duration_minutes: Optional[int]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    supply_order_id: str
    licensee_id: str
    claim_type: str
    description: str
    status: str
    info_request_count: int
    decision: Optional[str]
    decision_note: Optional[str]
    chargeback_cents: Optional[int]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartsOrder(TypedDict):
    id: str
    claim_id: str
    sku: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int
