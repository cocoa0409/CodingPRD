"""Domain types: entity TypedDicts, status enums, role enum for the Cookie Program API."""
from enum import Enum
from typing import Optional
from typing import TypedDict


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SELLING = "SELLING"
    RECONCILIATION = "RECONCILIATION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TroopStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class OrderKind(str, Enum):
    INITIAL = "INITIAL"
    REPLENISHMENT = "REPLENISHMENT"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    REJECTED = "REJECTED"


class PoStatus(str, Enum):
    DRAFT = "DRAFT"
    ORDERED = "ORDERED"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SHIPPER_SIGNED = "SHIPPER_SIGNED"
    RECEIVER_SIGNED = "RECEIVER_SIGNED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class SitePosture(str, Enum):
    DRAFT = "DRAFT"
    RECEIVING = "RECEIVING"
    FULL = "FULL"
    FROZEN = "FROZEN"


class BoothRequestMode(str, Enum):
    LOTTERY = "LOTTERY"
    FIRST_COME = "FIRST_COME"


class BoothRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    UNCOLLECTED = "UNCOLLECTED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class FulfillmentType(str, Enum):
    SHIPPED = "SHIPPED"
    IN_PERSON = "IN_PERSON"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    FORFEITED = "FORFEITED"


class IncentiveTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class AllergenTag(str, Enum):
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    MILK = "MILK"
    EGG = "EGG"
    WHEAT = "WHEAT"
    SOY = "SOY"
    SESAME = "SESAME"


class UserRole(str, Enum):
    COUNCIL_ADMIN = "CouncilAdmin"
    TROOP_LEADER = "TroopLeader"


class CookieSeason(TypedDict):
    id: str
    code: str
    name: str
    status: str
    ordering_opens_at: str
    ordering_closes_at: str
    initial_commit_units: int
    pending_commit_units: int
    purchased_units: int
    remaining_units: int
    forecast_attainment_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Troop(TypedDict):
    id: str
    troop_number: str
    name: str
    status: str
    service_unit: str
    created_at: str
    updated_at: str
    version: int


class CookieProduct(TypedDict):
    id: str
    season_id: str
    variety_code: str
    name: str
    unit_price_cents: int
    troop_proceeds_cents: int
    allergen_tags: list
    packages_per_case: int
    created_at: str
    updated_at: str
    version: int


class TroopAccount(TypedDict):
    id: str
    troop_id: str
    season_id: str
    balance_cents: int
    proceeds_accrued_cents: int
    uncollected_amount_cents: int
    deposit_cents: int
    created_at: str
    updated_at: str
    version: int


class CookieOrder(TypedDict):
    id: str
    season_id: str
    troop_id: str
    kind: str
    status: str
    total_units: int
    total_amount_cents: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CookieOrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    package_qty: int
    created_at: str
    updated_at: str
    version: int


class DistributionSite(TypedDict):
    id: str
    season_id: str
    name: str
    address: str
    capacity_units: int
    received_units: int
    hold_units: int
    available_units: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class BakerPurchaseOrder(TypedDict):
    id: str
    season_id: str
    baker_name: str
    product_id: str
    quantity: int
    delivery_site_id: str
    status: str
    delivered_qty: int
    created_at: str
    updated_at: str
    version: int


class InventoryTransfer(TypedDict):
    id: str
    season_id: str
    source_troop_id: Optional[str]
    dest_troop_id: Optional[str]
    site_id: Optional[str]
    product_id: str
    package_qty: int
    status: str
    shipper_signed_by_troop_id: Optional[str]
    receiver_signed_by_troop_id: Optional[str]
    counter_transfer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoothLocation(TypedDict):
    id: str
    season_id: str
    host_business_name: str
    address: str
    host_permission_granted: bool
    blackout_dates: list
    created_at: str
    updated_at: str
    version: int


class BoothSlot(TypedDict):
    id: str
    location_id: str
    start_at: str
    end_at: str
    capacity_troops: int
    created_at: str
    updated_at: str
    version: int


class BoothRequest(TypedDict):
    id: str
    slot_id: str
    troop_id: str
    mode: str
    lottery_rank: Optional[int]
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DigitalOrder(TypedDict):
    id: str
    season_id: str
    troop_id: str
    customer_email: str
    fulfillment_type: str
    donation_units: int
    payment_status: str
    fulfillment_status: str
    total_amount_cents: int
    items: list
    created_at: str
    updated_at: str
    version: int


class ParticipantAgreement(TypedDict):
    id: str
    troop_id: str
    season_id: str
    participant_name: str
    parent_name: str
    signed_responsibility: bool
    assigned_packages: int
    paid_amount_cents: int
    outstanding_cents: int
    incentive_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict):
    id: str
    season_id: str
    product_id: str
    reason: str
    effective_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
