"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    DEALER_AGENT = "DealerAgent"
    CUSTOMER = "Customer"
    PRICING_MANAGER = "PricingManager"
    REPOSITION_DRIVER = "RepositionDriver"
    FINANCE_REVIEWER = "FinanceReviewer"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class LocationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EquipmentUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    OUT = "OUT"
    REPOSITIONING = "REPOSITIONING"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class EquipmentType(str, Enum):
    TRUCK_10FT = "TRUCK_10FT"
    TRUCK_15FT = "TRUCK_15FT"
    TRUCK_26FT = "TRUCK_26FT"
    TRAILER_4X8 = "TRAILER_4X8"
    TRAILER_6X12 = "TRAILER_6X12"
    TOW_DOLLY = "TOW_DOLLY"


class GeoZone(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"
    CENTRAL = "CENTRAL"


class Season(str, Enum):
    PEAK = "PEAK"
    SHOULDER = "SHOULDER"
    OFF_PEAK = "OFF_PEAK"


class LaneRateStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RentalKind(str, Enum):
    ROUND_TRIP = "ROUND_TRIP"
    ONE_WAY = "ONE_WAY"


class ReservationStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    REASSIGNED = "REASSIGNED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    NO_SHOW = "NO_SHOW"


class TowCheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_REQUIRED = "NOT_REQUIRED"


class HitchClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"
    CLASS_IV = "CLASS_IV"
    NONE = "NONE"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    SETTLED = "SETTLED"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class TaskStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class EventType(str, Enum):
    CREATED = "CREATED"
    CONFIRMED = "CONFIRMED"
    REASSIGNED = "REASSIGNED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    NO_SHOW = "NO_SHOW"


class Dealer(TypedDict, total=False):
    id: str
    dealer_code: str
    name: str
    location_id: str
    commission_rate_override: Optional[float]
    status: str
    allocated_unit_count: int
    performance_score: float
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict, total=False):
    id: str
    location_code: str
    city: str
    geo_zone: str
    storage_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict, total=False):
    id: str
    unit_code: str
    equipment_type: str
    current_dealer_id: str
    current_location_id: str
    status: str
    status_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VehicleProfile(TypedDict, total=False):
    id: str
    label: str
    make: str
    model: str
    year: int
    curb_weight_lbs: int
    tow_capacity_lbs: int
    hitch_class: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    vehicle_profile_id: str
    driver_license_verified: bool
    created_at: str
    updated_at: str
    version: int


class LaneRate(TypedDict, total=False):
    id: str
    origin_location_id: str
    dest_location_id: str
    equipment_type: str
    season: str
    base_rate_cents: int
    reposition_surcharge_cents: int
    imbalance_factor: float
    commission_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    customer_id: str
    origin_dealer_id: str
    origin_location_id: str
    dest_location_id: str
    equipment_type: str
    rental_kind: str
    pickup_date: str
    dropoff_date: str
    season: str
    rental_days: int
    status: str
    price_snapshot: Dict[str, Any]
    tow_check_result: str
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict, total=False):
    id: str
    reservation_id: str
    equipment_unit_id: str
    checkout_dealer_id: str
    status: str
    checkout_at: str
    returned_at: Optional[str]
    actual_days: Optional[int]
    return_location_id: str
    late_fee_cents: int
    damage_charge_cents: int
    total_settled_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DamageProtectionPlan(TypedDict, total=False):
    id: str
    agreement_id: str
    tier: str
    premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    agreement_id: str
    claimed_amount_cents: int
    status: str
    approved_amount_cents: Optional[int]
    resolution_note: Optional[str]
    filer_user_id: str
    created_at: str
    updated_at: str
    version: int


class RepositionTask(TypedDict, total=False):
    id: str
    equipment_unit_id: str
    from_location_id: str
    to_location_id: str
    status: str
    assigned_driver_id: Optional[str]
    estimated_reposition_cost_cents: int
    executed_reposition_cost_cents: Optional[int]
    scheduled_after: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit row: carries id + created_at ONLY — no updated_at, no version.
class ReservationEvent(TypedDict, total=False):
    id: str
    reservation_id: str
    event_type: str
    from_dealer_id: Optional[str]
    to_dealer_id: Optional[str]
    note: Optional[str]
    created_at: str


class CrossSellOrder(TypedDict, total=False):
    id: str
    dealer_id: str
    agreement_id: Optional[str]
    line_items: List[Dict[str, Any]]
    storage_months: int
    supplies_subtotal_cents: int
    storage_charge_cents: int
    bundle_discount_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class DealerSettlement(TypedDict, total=False):
    id: str
    dealer_id: str
    period: str
    status: str
    gross_rental_cents: int
    commission_cents: int
    cross_sell_commission_cents: int
    clawback_cents: int
    net_cents: int
    created_at: str
    updated_at: str
    version: int
