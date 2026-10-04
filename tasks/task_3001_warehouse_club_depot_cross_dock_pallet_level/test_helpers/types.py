"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    REGIONAL_OPS = "RegionalOps"
    CATEGORY_MANAGER = "CategoryManager"
    DEPOT_MANAGER = "DepotManager"
    DEPOT_PLANNER = "DepotPlanner"
    MEMBERSHIP_DESK = "MembershipDesk"
    VENDOR_REP = "VendorRep"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class ClubPosture(str, Enum):
    NORMAL = "NORMAL"
    CONSTRAINED = "CONSTRAINED"
    FROZEN = "FROZEN"


class ItemStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DELETION_REVIEW = "DELETION_REVIEW"
    DISCONTINUED = "DISCONTINUED"


class ItemType(str, Enum):
    REGULAR = "REGULAR"
    TREASURE_HUNT = "TREASURE_HUNT"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class PalletStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    STRANDED = "STRANDED"
    RECONCILED = "RECONCILED"


class CrossDockRunStatus(str, Enum):
    OPEN = "OPEN"
    COMMITTED = "COMMITTED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    SHIPPED = "SHIPPED"
    VOIDED = "VOIDED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MemberTier(str, Enum):
    GOLD_STAR = "GOLD_STAR"
    EXECUTIVE = "EXECUTIVE"


class PurchaseStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"


class MarkdownDecisionType(str, Enum):
    SELL_THROUGH = "SELL_THROUGH"
    MARKDOWN = "MARKDOWN"


class ComplaintCategory(str, Enum):
    QUALITY = "QUALITY"
    AVAILABILITY = "AVAILABILITY"
    PRICING = "PRICING"
    SAFETY = "SAFETY"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ChargebackReason(str, Enum):
    LATE_CHECKIN = "LATE_CHECKIN"
    NO_SHOW = "NO_SHOW"
    OVER_PALLET_COUNT = "OVER_PALLET_COUNT"


class ChargebackStatus(str, Enum):
    ASSESSED = "ASSESSED"
    APPEALED = "APPEALED"
    WAIVED = "WAIVED"
    CONFIRMED = "CONFIRMED"


class Department(str, Enum):
    GAS = "GAS"
    PHARMACY = "PHARMACY"
    OPTICAL = "OPTICAL"


class Region(TypedDict):
    id: str
    name: str
    code: str
    avg_member_income_cents: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    vendor_code: str
    status: str
    compliance_score_bp: int
    total_chargeback_cents: int
    created_at: str
    updated_at: str
    version: int


class Club(TypedDict):
    id: str
    region_id: str
    name: str
    club_number: int
    floor_slot_capacity: int
    member_base: int
    posture: str
    allocated_slot_count: int
    ancillary_flags: dict
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    vendor_id: str
    sku: str
    description: str
    case_pack_qty: int
    pallet_length_in: float
    pallet_width_in: float
    cases_per_layer: int
    max_layers: int
    item_type: str
    status: str
    pallet_qty_units: int
    pallets_per_slot: int
    member_purchase_cap: int
    sell_through_target_pct: int
    exit_window_date: Optional[str]
    complaint_weighted_score: float
    complaint_count: int
    created_at: str
    updated_at: str
    version: int


class Depot(TypedDict):
    id: str
    region_id: str
    name: str
    dock_count: int
    dock_hours_open: str
    dock_hours_close: str
    slot_length_minutes: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    depot_id: str
    vendor_id: str
    delivery_date: str
    start_time: str
    end_time: str
    pallet_count: int
    status: str
    checked_in_at: Optional[str]
    unload_fee_cents: int
    chargeback_cents: int
    created_at: str
    updated_at: str
    version: int


class Pallet(TypedDict):
    id: str
    appointment_id: str
    item_id: str
    unit_qty: int
    received_at: str
    received_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrossDockRun(TypedDict):
    id: str
    depot_id: str
    run_date: str
    cutoff_time: str
    status: str
    committed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    cross_dock_run_id: str
    pallet_id: str
    club_id: str
    allocation_score: float
    floor_slots_reserved: int
    run_version: int
    status: str
    void_reason: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    club_id: str
    membership_number: str
    tier: str
    household_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict):
    id: str
    member_id: str
    club_id: str
    item_id: str
    unit_qty: int
    purchased_at: str
    cap_window: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MarkdownDecision(TypedDict):
    id: str
    item_id: str
    decision: str
    markdown_pct: Optional[int]
    note: str
    sell_through_pct: int
    decided_by_role: str
    decided_at: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    member_id: str
    item_id: str
    category: str
    created_on: str
    weight: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Chargeback(TypedDict):
    id: str
    vendor_id: str
    appointment_id: str
    amount_cents: int
    reason: str
    status: str
    assessed_at: str
    created_at: str
    updated_at: str
    version: int


class DepartmentSale(TypedDict):
    id: str
    club_id: str
    member_id: str
    department: str
    amount_cents: int
    sold_on: str
    created_at: str
    updated_at: str
    version: int
