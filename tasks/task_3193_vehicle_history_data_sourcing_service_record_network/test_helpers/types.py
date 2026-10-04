"""Domain types: entity shapes, status enums, and roles.

All monetary quantities are integer cents. Every primary resource carries
``id`` (UUID), ``created_at``, ``updated_at`` and ``version`` per the PRD's
common-resource-properties section.
"""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    SOURCE_OPERATOR = "SourceOperator"
    SHOP_OPERATOR = "ShopOperator"
    VEHICLE_OWNER = "VehicleOwner"
    DEALER_AGENT = "DealerAgent"
    GUARANTEE_ADMIN = "GuaranteeAdmin"


class SourceStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ShopStatus(str, Enum):
    APPLIED = "APPLIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    VOIDED = "VOIDED"


class CorrectionStatus(str, Enum):
    OPEN = "OPEN"
    AWAITING_SOURCE = "AWAITING_SOURCE"
    VERIFIED = "VERIFIED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DELISTED = "DELISTED"


class GuaranteeStatus(str, Enum):
    UNENROLLED = "UNENROLLED"
    ENROLLED = "ENROLLED"
    VOIDED = "VOIDED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DENIED = "DENIED"
    PAID = "PAID"


class CanonicalBrand(str, Enum):
    NONE = "NONE"
    CLEAN = "CLEAN"
    LEMON = "LEMON"
    FLOOD = "FLOOD"
    REBUILT = "REBUILT"
    SALVAGE = "SALVAGE"


BRAND_SEVERITY = {
    "NONE": 0,
    "CLEAN": 1,
    "LEMON": 2,
    "FLOOD": 3,
    "REBUILT": 4,
    "SALVAGE": 5,
}


class Network(TypedDict, total=False):
    id: str
    name: str
    epoch_index: int
    brand_lexicon: dict
    guarantee_payout_cap_cents: int
    enrolled_listing_count: int
    created_at: str
    updated_at: str
    version: int


class DataSource(TypedDict, total=False):
    id: str
    network_id: str
    source_type: str
    jurisdiction: str
    status: str
    reliability_score: int
    consecutive_missed_epochs: int
    suspended_epoch_index: Optional[int]
    record_rejection_streak: int
    created_at: str
    updated_at: str
    version: int


class Shop(TypedDict, total=False):
    id: str
    network_id: str
    legal_name: str
    status: str
    suspended_epoch_index: Optional[int]
    data_source_id: Optional[str]
    reporting_tool_tier: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    network_id: str
    vin: str
    canonical_brand: str
    brand_severity: int
    max_confirmed_accident_severity: int
    active_record_count: int
    superseded_record_count: int
    created_at: str
    updated_at: str
    version: int


class HistoryRecord(TypedDict, total=False):
    id: str
    network_id: str
    vehicle_id: str
    vin: str
    source_id: str
    record_type: str
    jurisdiction: Optional[str]
    raw_brand_text: Optional[str]
    event_date: str
    damage_severity: Optional[int]
    odometer_reading: Optional[int]
    reported_cost_cents: Optional[int]
    payload_ref: str
    idempotency_key: str
    dedupe_group_key: Optional[str]
    match_method: str
    confidence_score: Optional[int]
    confidence_level: Optional[str]
    canonical_brand: Optional[str]
    brand_severity: Optional[int]
    status: str
    superseded_by_record_id: Optional[str]
    submitted_epoch_index: int
    created_at: str
    updated_at: str
    version: int


class CorrectionRequest(TypedDict, total=False):
    id: str
    network_id: str
    vehicle_id: str
    target_record_id: str
    requester_role: str
    requester_shop_id: Optional[str]
    reason: str
    corrected_record: Optional[dict]
    status: str
    resolution_action: Optional[str]
    opened_epoch_index: int
    source_deadline_epoch: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ConsumerAccount(TypedDict, total=False):
    id: str
    network_id: str
    email: str
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict, total=False):
    id: str
    network_id: str
    legal_name: str
    subscription_tier: str
    status: str
    subscription_started_epoch: Optional[int]
    period_reports_used: int
    period_overage_units: int
    invoice_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class InventoryListing(TypedDict, total=False):
    id: str
    network_id: str
    dealer_id: str
    vehicle_id: str
    asking_price_cents: int
    status: str
    guarantee_status: str
    enrolled_brand: Optional[str]
    window_start_epoch: Optional[int]
    window_end_epoch: Optional[int]
    created_at: str
    updated_at: str
    version: int


class GuaranteeClaim(TypedDict, total=False):
    id: str
    network_id: str
    dealer_id: str
    listing_id: str
    claimant_name: str
    claim_reason: str
    status: str
    payout_cents: int
    payout_epoch_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ReportOrder(TypedDict, total=False):
    id: str
    network_id: str
    vehicle_id: str
    product: str
    buyer_consumer_id: Optional[str]
    buyer_dealer_id: Optional[str]
    price_cents: int
    snapshot: dict
    status: str
    created_at: str
    updated_at: str
    version: int
