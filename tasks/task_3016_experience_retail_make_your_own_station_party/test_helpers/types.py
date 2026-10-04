"""Domain types: entity shapes, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    WORKSHOP_ASSOCIATE = "WorkshopAssociate"
    PARTY_HOST = "PartyHost"
    STORE_MANAGER = "StoreManager"


class WorkshopSessionStatus(str, Enum):
    SELECT = "SELECT"
    SELECTED = "SELECTED"
    STUFFED = "STUFFED"
    SOUNDED = "SOUNDED"
    BATHED = "BATHED"
    DRESSED = "DRESSED"
    PAID = "PAID"
    ABANDONED = "ABANDONED"


class StuffedAnimalStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    LOST_REPORTED = "LOST_REPORTED"
    RECOVERED = "RECOVERED"


class PartyReservationStatus(str, Enum):
    QUOTED = "QUOTED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PartyGuestStatus(str, Enum):
    INVITED = "INVITED"
    CONFIRMED = "CONFIRMED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AppointmentBlockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class BuildShipOrderStatus(str, Enum):
    PLACED = "PLACED"
    IN_ASSEMBLY = "IN_ASSEMBLY"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    HANDED_TO_CARRIER = "HANDED_TO_CARRIER"
    CANCELLED = "CANCELLED"


class GiftCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    DISABLED = "DISABLED"


class StationType(str, Enum):
    SELECT = "SELECT"
    STUFF = "STUFF"
    SOUND = "SOUND"
    BATHE = "BATHE"
    DRESS = "DRESS"


class ConsumableType(str, Enum):
    STUFFING_FIBER = "STUFFING_FIBER"
    SOUND_CHIP = "SOUND_CHIP"


class OriginType(str, Enum):
    WALK_IN = "WALK_IN"
    PARTY = "PARTY"
    BUILD_SHIP = "BUILD_SHIP"


class PackageTier(str, Enum):
    BASIC = "BASIC"
    CELEBRATION = "CELEBRATION"
    ULTIMATE = "ULTIMATE"


class StaffingMode(str, Enum):
    STAFF_HOSTED = "STAFF_HOSTED"
    SELF_GUIDED = "SELF_GUIDED"


class PayTender(str, Enum):
    CASH = "CASH"
    GIFT_CARD = "GIFT_CARD"
    GIFT_CARD_LINKED = "GIFT_CARD_LINKED"


class RoleTitle(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    PARTY_HOST = "PARTY_HOST"
    MANAGER = "MANAGER"


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Store(CommonFields):
    name: str
    party_room_count: int


class Customer(CommonFields):
    email: str
    full_name: str


class StaffMember(CommonFields):
    store_id: str
    display_name: str
    role_title: str


class Station(CommonFields):
    store_id: str
    station_type: str
    capacity: int


class PlushModel(CommonFields):
    name: str
    sku: str
    base_price_cents: int
    is_licensed: bool
    required_stuffing_grams: int
    sound_chip_compatible: bool


class Consumable(CommonFields):
    store_id: str
    consumable_type: str
    on_hand_qty: int
    initial_qty: int


class CollectionDrop(CommonFields):
    name: str
    plush_model_id: str
    drop_start: str
    drop_end: str
    per_customer_limit: int
    total_units: int
    units_claimed: int


class WorkshopSession(CommonFields):
    store_id: str
    customer_id: str
    plush_model_id: str
    collection_drop_id: Optional[str]
    origin_type: str
    party_reservation_id: Optional[str]
    build_ship_order_id: Optional[str]
    assigned_station_id: Optional[str]
    stuffed_animal_id: Optional[str]
    stuffing_grams_used: int
    sound_chip_used: bool
    total_price_cents: int
    started_at: str
    status: str


class StuffedAnimal(CommonFields):
    customer_id: str
    plush_model_id: str
    origin_workshop_session_id: str
    birth_cert_name: Optional[str]
    birth_cert_birth_date: Optional[str]
    status: str


class PartyReservation(CommonFields):
    store_id: str
    customer_id: str
    party_start: str
    duration_minutes: int
    guest_count: int
    package_tier: str
    staffing_mode: str
    deposit_amount_cents: int
    paid_amount_cents: int
    final_amount_due_cents: int
    status: str


class PartyGuest(CommonFields):
    party_reservation_id: str
    guest_name: str
    workshop_session_id: Optional[str]
    status: str


class AppointmentBlock(CommonFields):
    store_id: str
    party_reservation_id: str
    block_start: str
    block_end: str
    reserved_host_id: Optional[str]
    status: str


class BuildShipOrder(CommonFields):
    store_id: str
    customer_id: str
    plush_model_id: str
    sound_chip_requested: bool
    recipient_name: str
    workshop_session_id: Optional[str]
    carrier_code: Optional[str]
    tracking_number: Optional[str]
    handed_over_at: Optional[str]
    status: str


class GiftCard(CommonFields):
    code: str
    balance_cents: int
    initial_balance_cents: int
    status: str


class Registry(CommonFields):
    customer_id: str
    name: str
    linked_animal_ids: List[str]
    linked_gift_card_ids: List[str]
