"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SELLER_AGENT = "SellerAgent"
    YARD_OPERATOR = "YardOperator"
    AUCTIONEER = "Auctioneer"
    BUYER = "Buyer"
    TITLE_CLERK = "TitleClerk"


class YardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class SellerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SellerType(str, Enum):
    INSURER = "INSURER"
    DEALER = "DEALER"
    FLEET = "FLEET"


class FeeSchedule(str, Enum):
    STANDARD = "STANDARD"
    VOLUME = "VOLUME"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MemberTier(str, Enum):
    BASIC = "BASIC"
    PREMIER = "PREMIER"
    BUSINESS = "BUSINESS"


class LicenseType(str, Enum):
    DEALER = "DEALER"
    DISMANTLER = "DISMANTLER"
    SALVAGE_BROKER = "SALVAGE_BROKER"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class LotType(str, Enum):
    STANDARD = "STANDARD"
    DEALER_ONLY = "DEALER_ONLY"
    DISMANTLER_ONLY = "DISMANTLER_ONLY"
    EXPORT_ONLY = "EXPORT_ONLY"


class SaleType(str, Enum):
    PURE = "PURE"
    MINIMUM_BID = "MINIMUM_BID"
    ON_APPROVAL = "ON_APPROVAL"


class PrimaryDamage(str, Enum):
    FRONT = "FRONT"
    REAR = "REAR"
    SIDE = "SIDE"
    TOP = "TOP"
    MECHANICAL = "MECHANICAL"
    FLOOD = "FLOOD"
    FIRE = "FIRE"
    NONE = "NONE"


class RunAndDriveStatus(str, Enum):
    RUN_AND_DRIVE = "RUN_AND_DRIVE"
    STARTS = "STARTS"
    STATIONARY = "STATIONARY"
    UNKNOWN = "UNKNOWN"


class TitleBrand(str, Enum):
    NONE = "NONE"
    REBUILT = "REBUILT"


class VehicleStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    AWAITING_CONDITION = "AWAITING_CONDITION"
    SALE_READY = "SALE_READY"
    LISTED = "LISTED"
    LIVE = "LIVE"
    SOLD = "SOLD"
    ON_APPROVAL_PENDING = "ON_APPROVAL_PENDING"
    RELEASED = "RELEASED"
    LOADED_OUT = "LOADED_OUT"
    CANCELLED = "CANCELLED"


class TitleType(str, Enum):
    CLEAN = "CLEAN"
    SALVAGE = "SALVAGE"
    REBUILT = "REBUILT"
    NON_REPAIRABLE = "NON_REPAIRABLE"
    PARTS_ONLY = "PARTS_ONLY"
    CERTIFICATE_OF_DESTRUCTION = "CERTIFICATE_OF_DESTRUCTION"


class Transferability(str, Enum):
    TRANSFERABLE = "TRANSFERABLE"
    EXPORT_ONLY = "EXPORT_ONLY"
    NON_TRANSFERABLE = "NON_TRANSFERABLE"


class TitleStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    TRANSFERRED = "TRANSFERRED"


class AuctionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"


class AuctionItemStatus(str, Enum):
    QUEUED = "QUEUED"
    LIVE = "LIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BidType(str, Enum):
    PRELIM = "PRELIM"
    LIVE = "LIVE"


class SaleStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class GatePassStatus(str, Enum):
    ISSUED = "ISSUED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"


class ExportDocumentType(str, Enum):
    BILL_OF_LADING = "BILL_OF_LADING"
    EXPORT_DECLARATION = "EXPORT_DECLARATION"
    CUSTOMS_MANIFEST = "CUSTOMS_MANIFEST"


class ExportDocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class Yard(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    daily_storage_rate_cents: int
    free_storage_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Seller(TypedDict, total=False):
    id: str
    name: str
    seller_type: str
    fee_schedule: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    home_state: str
    tier: str
    country_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    member_id: str
    state_code: str
    license_type: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    seller_id: str
    yard_id: str
    vin: str
    year: int
    make: str
    model: str
    lot_type: str
    reserve_price_cents: int
    sale_type: str
    damage_codes: list
    primary_damage: str
    run_and_drive_status: str
    image_ids: list
    image_count: int
    odometer_reading: int
    title_brand: str
    assigned_at: str
    received_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TitleRecord(TypedDict, total=False):
    id: str
    vehicle_id: str
    jurisdiction_state: str
    title_type: str
    received_at: str
    transferability: str
    late: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Auction(TypedDict, total=False):
    id: str
    name: str
    scheduled_start: str
    status: str
    current_sequence_number: int
    created_at: str
    updated_at: str
    version: int


class AuctionItem(TypedDict, total=False):
    id: str
    auction_id: str
    vehicle_id: str
    sequence_number: Optional[int]
    prelim_high_bid_cents: int
    prelim_high_bidder_id: Optional[str]
    high_bid_cents: int
    high_bidder_id: Optional[str]
    reserve_met: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    # Immutable event row: id + created_at only (no updated_at, no version).
    id: str
    created_at: str
    auction_item_id: str
    member_id: str
    amount_cents: int
    bid_type: str
    is_winning: bool
    placed_at: str


class Sale(TypedDict, total=False):
    id: str
    vehicle_id: str
    auction_item_id: str
    winner_member_id: str
    winning_bid_cents: int
    buyer_fee_cents: int
    gate_pass_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GatePass(TypedDict, total=False):
    id: str
    sale_id: str
    slot_start: str
    slot_end: str
    status: str
    storage_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    sale_id: str
    seller_id: str
    gross_proceeds_cents: int
    seller_fee_cents: int
    storage_recovery_cents: int
    title_late_penalty_cents: int
    net_proceeds_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExportDocument(TypedDict, total=False):
    id: str
    sale_id: str
    document_type: str
    destination_country: str
    status: str
    created_at: str
    updated_at: str
    version: int
