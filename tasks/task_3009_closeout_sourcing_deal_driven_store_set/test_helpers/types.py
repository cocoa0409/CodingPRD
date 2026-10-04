"""Domain types for the Closeout Deal Stores API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ADMIN = "Admin"
    SOURCING_BUYER = "SourcingBuyer"
    SAFETY_OFFICER = "SafetyOfficer"
    PRICING_LEAD = "PricingLead"
    ALLOCATION_MANAGER = "AllocationManager"
    STORE_MANAGER = "StoreManager"
    CLUB_MEMBER = "ClubMember"
    ANONYMOUS = "Anonymous"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PerformanceTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ComparisonRule(str, Enum):
    WAS_NOW_WINDOW = "WAS_NOW_WINDOW"
    MSRP_REFERENCE = "MSRP_REFERENCE"
    COMPARISON_PROHIBITED = "COMPARISON_PROHIBITED"


class SourceType(str, Enum):
    MFR_OVERRUN = "MFR_OVERRUN"
    PACKAGE_CHANGE = "PACKAGE_CHANGE"
    INSURANCE_SALVAGE = "INSURANCE_SALVAGE"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    MIXED = "MIXED"


class LotCommercialStatus(str, Enum):
    SOURCED = "SOURCED"
    SCREENING = "SCREENING"
    CLEARED = "CLEARED"
    PRICED = "PRICED"
    ON_SALE = "ON_SALE"
    DISPOSITION_REVIEW = "DISPOSITION_REVIEW"
    BLOCKED = "BLOCKED"
    CLOSED_SOLD_OUT = "CLOSED_SOLD_OUT"
    CLOSED_LIQUIDATED = "CLOSED_LIQUIDATED"
    CLOSED_SCRAPPED = "CLOSED_SCRAPPED"


class LotSafetyStatus(str, Enum):
    PENDING_SCREEN = "PENDING_SCREEN"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class ScreeningStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class ScreeningResult(str, Enum):
    PASSED = "PASSED"
    FAILED_RECALL = "FAILED_RECALL"
    FAILED_EXPIRATION = "FAILED_EXPIRATION"
    FAILED_CONDITION = "FAILED_CONDITION"


class CheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NA = "NA"


class AllocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class AisleAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class MemberTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class PurchaseStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"


class PricingVariant(str, Enum):
    EVENT = "EVENT"
    STANDARD = "STANDARD"
    GUEST = "GUEST"


class DispositionAction(str, Enum):
    MARKDOWN = "MARKDOWN"
    LIQUIDATE = "LIQUIDATE"
    SCRAP = "SCRAP"


class DispositionStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts.  Every primary resource carries id / created_at /
# updated_at / version per the PRD's common-resource contract.
# ---------------------------------------------------------------------------


class Vendor(TypedDict, total=False):
    id: str
    name: str
    vendor_code: str
    created_at: str
    updated_at: str
    version: int


class JurisdictionRule(TypedDict, total=False):
    id: str
    jurisdiction_code: str
    comparison_rule: str
    window_days: Optional[int]
    required_offer_days: Optional[int]
    max_advertised_discount_pct: int
    member_discount_cap_pct: int
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    name: str
    store_code: str
    jurisdiction_id: str
    performance_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BuyLot(TypedDict, total=False):
    id: str
    vendor_id: str
    home_jurisdiction_id: str
    title: str
    source_type: str
    condition_grade: str
    quantity_total: int
    total_cost_cents: int
    est_sellable_qty: int
    comparison_price_cents: int
    vendor_msrp_cents: int
    pace_target_units_per_week: int
    created_by_user_id: str
    safety_status: str
    commercial_status: str
    retail_price_cents: Optional[int]
    advertises_comparison: bool
    sellable_qty_confirmed: Optional[int]
    landed_unit_cost_cents: int
    markdown_rounds: int
    on_sale_since: Optional[str]
    qty_pool: int
    qty_allocated_outstanding: int
    qty_sold: int
    qty_liquidated: int
    qty_scrapped: int
    created_at: str
    updated_at: str
    version: int


class SafetyScreening(TypedDict, total=False):
    id: str
    lot_id: str
    round_number: int
    screener_user_id: str
    status: str
    recall_check: Optional[str]
    expiration_check: Optional[str]
    condition_verified: Optional[bool]
    qty_grade_a: Optional[int]
    qty_grade_b: Optional[int]
    qty_grade_c: Optional[int]
    result: Optional[str]
    notes: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    lot_id: str
    store_id: str
    qty_requested: int
    qty_granted: int
    store_on_hand_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AisleAssignment(TypedDict, total=False):
    id: str
    store_id: str
    lot_id: str
    aisle_code: str
    daily_unit_limit: int
    valid_from: str
    valid_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyMember(TypedDict, total=False):
    id: str
    member_code: str
    tier: str
    home_store_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EarlyAccessEvent(TypedDict, total=False):
    id: str
    lot_id: str
    starts_at: str
    ends_at: str
    min_tier: str
    extra_discount_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict, total=False):
    id: str
    store_id: str
    lot_id: str
    member_id: Optional[str]
    qty: int
    pricing_variant: str
    discount_pct_applied: int
    unit_price_cents: int
    line_total_cents: int
    status: str
    refunded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disposition(TypedDict, total=False):
    id: str
    lot_id: str
    action: str
    markdown_pct: Optional[int]
    liquidator_ref: Optional[str]
    recovery_cents: Optional[int]
    status: str
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
