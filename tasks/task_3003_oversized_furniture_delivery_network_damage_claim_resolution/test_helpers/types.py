"""Domain types: entity TypedDicts, status enums, role enum for the
Oversize Freight Network API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    CUSTOMER = "Customer"
    HUB_OPERATOR = "HubOperator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    SUPPLIER_REP = "SupplierRep"
    CARRIER_REP = "CarrierRep"


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class ItemStatus(str, Enum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class FreightClass(str, Enum):
    PARCEL_ELIGIBLE = "PARCEL_ELIGIBLE"
    LTL_250 = "LTL_250"
    LTL_150 = "LTL_150"
    LTL_125 = "LTL_125"
    LTL_92_5 = "LTL_92_5"


class HubStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ServiceLevel(str, Enum):
    THRESHOLD = "THRESHOLD"
    ROOM_OF_CHOICE = "ROOM_OF_CHOICE"


class OrderState(str, Enum):
    PENDING = "PENDING"
    ROUTED = "ROUTED"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class FulfillmentState(str, Enum):
    NONE = "NONE"
    SCHEDULED = "SCHEDULED"
    FULFILLED = "FULFILLED"
    RETURNED = "RETURNED"


class LegMode(str, Enum):
    PARCEL = "PARCEL"
    LTL = "LTL"
    OWNED_FINAL_MILE = "OWNED_FINAL_MILE"


class FulfillmentMode(str, Enum):
    PARCEL = "PARCEL"
    DROP_SHIP = "DROP_SHIP"
    OWNED_FINAL_MILE = "OWNED_FINAL_MILE"


class ShipmentState(str, Enum):
    CREATED = "CREATED"
    TENDERED = "TENDERED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_HUB = "AT_HUB"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"


class LinehaulStatus(str, Enum):
    PLANNED = "PLANNED"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    MISSED = "MISSED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ClaimantRole(str, Enum):
    CUSTOMER = "CUSTOMER"
    HUB_INSPECTOR = "HUB_INSPECTOR"


class Concealment(str, Enum):
    CONCEALED = "CONCEALED"
    VISIBLE_AT_DELIVERY = "VISIBLE_AT_DELIVERY"


class ResolutionType(str, Enum):
    REPLACEMENT_PART = "REPLACEMENT_PART"
    REPAIR = "REPAIR"
    FULL_REPLACEMENT = "FULL_REPLACEMENT"


class LiabilityParty(str, Enum):
    SUPPLIER = "SUPPLIER"
    CARRIER = "CARRIER"


class DamageClaimStatus(str, Enum):
    OPEN = "OPEN"
    INSPECTION = "INSPECTION"
    DETERMINATION = "DETERMINATION"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class ChargebackStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"
    REVERSED = "REVERSED"


class ChargebackReasonCode(str, Enum):
    CONCEALED_DAMAGE = "CONCEALED_DAMAGE"
    REPAIR_OVERRUN = "REPAIR_OVERRUN"
    FULL_REPLACEMENT = "FULL_REPLACEMENT"


class ReturnReason(str, Enum):
    DAMAGE = "DAMAGE"
    BUYERS_REMORSE = "BUYERS_REMORSE"
    WRONG_ITEM = "WRONG_ITEM"


class ReturnDisposition(str, Enum):
    FIELD_DISPOSAL = "FIELD_DISPOSAL"
    RETURN_TO_HUB = "RETURN_TO_HUB"


class ReturnAuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


# All entities carry common fields: id, created_at, updated_at, version.

class Supplier(TypedDict, total=False):
    id: str
    supplier_code: str
    legal_name: str
    drop_ship_enabled: bool
    lead_time_days: int
    compliance_score: float
    on_time_ship_rate: float
    chargeback_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    supplier_id: str
    sku: str
    dim_length_in: float
    dim_width_in: float
    dim_height_in: float
    weight_lb: float
    declared_value_cents: int
    white_glove_eligible: bool
    cube_score: float
    freight_class: str
    declared_girth_in: int
    parcel_ok: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Hub(TypedDict, total=False):
    id: str
    hub_code: str
    name: str
    serves_zones: List[str]
    white_glove_capable: bool
    daily_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    destination_zone: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    item_id: str
    service_level: str
    shipping_amount_cents: int
    oversized_surcharge_cents: int
    handling_fee_cents: int
    order_total_cents: int
    order_state: str
    fulfillment_state: str
    created_at: str
    updated_at: str
    version: int


class FreightLane(TypedDict, total=False):
    id: str
    leg_mode: str
    dest_zone: str
    base_rate_cents: int
    per_lb_rate_cents: int
    transit_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    order_id: str
    item_id: str
    supplier_id: str
    hub_id: Optional[str]
    linehaul_id: Optional[str]
    fulfillment_mode: str
    leg_mode: str
    promised_date: Optional[str]
    actual_ship_date: Optional[str]
    promised_ship_date: Optional[str]
    linehaul_misses: int
    current_state: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Linehaul(TypedDict, total=False):
    id: str
    hub_id: str
    planned_arrival_date: str
    origin_ship_date: str
    capacity: int
    committed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryAppointment(TypedDict, total=False):
    id: str
    shipment_id: str
    service_level: str
    window_start: str
    window_end: str
    hub_id: str
    crew_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    shipment_id: str
    claimant_role: str
    concealment: str
    damage_pct: int
    is_structural: bool
    repair_cost_cents: int
    replacement_cost_cents: int
    resolution_type: Optional[str]
    liability_party: Optional[str]
    chargeback_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Chargeback(TypedDict, total=False):
    id: str
    damage_claim_id: str
    supplier_id: str
    shipment_id: str
    amount_cents: int
    reason_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict, total=False):
    id: str
    order_id: str
    reason: str
    reverse_haul_cost_cents: Optional[int]
    refurb_value_cents: Optional[int]
    disposition: Optional[str]
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
