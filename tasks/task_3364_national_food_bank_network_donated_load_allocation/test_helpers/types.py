"""Domain types for the Food Bank Load Allocation API.

Entity TypedDicts, status enums and the role enum, mirroring the resource
definitions and lifecycle states described in the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    MEMBER_FOOD_BANK = "MemberFoodBank"
    NETWORK_AUDITOR = "NetworkAuditor"


class CertificationStatus(str, Enum):
    PENDING_CERTIFICATION = "PENDING_CERTIFICATION"
    CERTIFIED = "CERTIFIED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class TransportAbility(str, Enum):
    NONE = "NONE"
    LOCAL = "LOCAL"
    REGIONAL = "REGIONAL"
    NATIONAL = "NATIONAL"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class DonorType(str, Enum):
    MANUFACTURER = "MANUFACTURER"
    RETAILER = "RETAILER"
    DISTRIBUTOR = "DISTRIBUTOR"


class ProductCategory(str, Enum):
    DRY_GOODS = "DRY_GOODS"
    PRODUCE = "PRODUCE"
    DAIRY = "DAIRY"
    FROZEN_PROTEIN = "FROZEN_PROTEIN"
    BAKERY = "BAKERY"


class StorageType(str, Enum):
    DRY = "DRY"
    REFRIGERATED = "REFRIGERATED"
    FROZEN = "FROZEN"


class DestinationRegion(str, Enum):
    NORTHEAST = "NORTHEAST"
    SOUTHEAST = "SOUTHEAST"
    MIDWEST = "MIDWEST"
    SOUTHWEST = "SOUTHWEST"
    WEST = "WEST"


class LoadStatus(str, Enum):
    POSTED = "POSTED"
    BIDDING = "BIDDING"
    AWARDED = "AWARDED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SafetyStatus(str, Enum):
    CLEAR = "CLEAR"
    HELD = "HELD"
    RECALLED = "RECALLED"


class FreightDecision(str, Enum):
    PENDING = "PENDING"
    COVERED = "COVERED"
    DECLINED = "DECLINED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"


class RejectionReason(str, Enum):
    WITHDRAWN_BY_MEMBER = "WITHDRAWN_BY_MEMBER"
    MEMBER_PROBATION = "MEMBER_PROBATION"
    MEMBER_SUSPENDED = "MEMBER_SUSPENDED"
    LOSING_BID = "LOSING_BID"
    LOAD_CANCELLED = "LOAD_CANCELLED"
    LOAD_SAFETY_HOLD = "LOAD_SAFETY_HOLD"
    FREIGHT_DECLINED = "FREIGHT_DECLINED"


class LedgerEntryType(str, Enum):
    GRANT = "GRANT"
    BID_HOLD = "BID_HOLD"
    BID_RELEASE = "BID_RELEASE"
    AWARD_DEBIT = "AWARD_DEBIT"
    AWARD_REFUND = "AWARD_REFUND"
    ACTIVITY_BONUS = "ACTIVITY_BONUS"
    RECALL_REFUND = "RECALL_REFUND"


class RecallStatus(str, Enum):
    OPEN = "OPEN"
    TRACING = "TRACING"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    DESTROYED = "DESTROYED"


class AuditType(str, Enum):
    STORAGE = "STORAGE"
    DISTRIBUTION = "DISTRIBUTION"
    REPORTING = "REPORTING"
    COMPREHENSIVE = "COMPREHENSIVE"


class AuditStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ProgramStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PickupFrequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"


class PickupStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


# common_fields: true — carries id + created_at + updated_at + version
class MemberFoodBank(TypedDict):
    id: str
    name: str
    state_code: str
    food_insecure_population: int
    storage_capacity_lbs: int
    refrigerated_capacity_lbs: int
    transport_ability: str
    certification_status: str
    share_balance: int
    share_reserved: int
    audit_score: int
    last_grant_epoch: Optional[str]
    active_bid_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class DonorAgreement(TypedDict):
    id: str
    donor_name: str
    donor_type: str
    product_category: str
    committed_lbs: int
    meal_equivalency_factor: float
    status: str
    freight_subsidy_pool_cents: int
    freight_subsidy_used_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class DonatedLoad(TypedDict):
    id: str
    donor_agreement_id: str
    product_category: str
    storage_type: str
    weight_lbs: int
    lot_code: str
    origin_zip: str
    destination_region: str
    distance_miles: int
    status: str
    safety_status: str
    awarded_bid_id: Optional[str]
    awarded_member_id: Optional[str]
    freight_estimate_cents: int
    freight_subsidy_cents: int
    member_freight_due_cents: int
    freight_decision: str
    delivery_window_start: Optional[str]
    delivery_window_end: Optional[str]
    delivered_lbs: int
    meal_equivalent: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class LoadBid(TypedDict):
    id: str
    load_id: str
    member_id: str
    shares_offered: int
    preference_rank: int
    can_self_transport: bool
    bid_status: str
    rejection_reason: Optional[str]
    submitted_round: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class ShareLedgerEntry(TypedDict):
    id: str
    member_id: str
    entry_type: str
    amount: int
    balance_after: int
    epoch: str
    reference_id: Optional[str]
    created_at: str


# common_fields: true
class ProductRecall(TypedDict):
    id: str
    donor_agreement_id: str
    lot_code: str
    product_category: str
    affected_lbs: int
    recall_status: str
    traced_load_count: int
    held_lbs: int
    opened_at: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class RecallHold(TypedDict):
    id: str
    recall_id: str
    load_id: str
    hold_status: str
    hold_reason: str
    created_at: str


# common_fields: true
class MemberAudit(TypedDict):
    id: str
    member_id: str
    audit_type: str
    storage_score: int
    distribution_score: int
    reporting_score: int
    weighted_score: float
    opened_by_user_id: str
    audit_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class StoreDonationProgram(TypedDict):
    id: str
    member_id: str
    store_name: str
    store_chain: str
    pickup_frequency: str
    expected_weekly_lbs: int
    program_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class StorePickup(TypedDict):
    id: str
    program_id: str
    scheduled_date: str
    window_start: str
    window_end: str
    pickup_status: str
    collected_lbs: int
    meal_equivalent: int
    created_at: str
    updated_at: str
    version: int
