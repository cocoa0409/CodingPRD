"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity definitions. Entities that carry the standard
system-managed field set expose id + created_at + updated_at + version;
the two append-only kinds (ChecklistItem, CashDrop) carry only id + created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StormStatus(str, Enum):
    WATCH = "WATCH"
    WARNING = "WARNING"
    ACTIVE = "ACTIVE"
    RECOVERY = "RECOVERY"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class MenuTier(str, Enum):
    FULL = "FULL"
    TIER1_NO_POWER = "TIER1_NO_POWER"
    TIER2_NO_WATER = "TIER2_NO_WATER"
    TIER3_NO_GAS = "TIER3_NO_GAS"


class AxisState(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


class CrewRole(str, Enum):
    GRILL_OP = "GRILL_OP"
    SERVER = "SERVER"
    SHIFT_LEAD = "SHIFT_LEAD"


class CrewMemberStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    INACTIVE = "INACTIVE"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssetKind(str, Enum):
    GENERATOR = "GENERATOR"
    MOBILE_KITCHEN = "MOBILE_KITCHEN"


class AssetStatus(str, Enum):
    IDLE = "IDLE"
    ALLOCATED = "ALLOCATED"
    RETURNED = "RETURNED"
    RETIRED = "RETIRED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class ActivationTier(str, Enum):
    TIER1_NO_POWER = "TIER1_NO_POWER"
    TIER2_NO_WATER = "TIER2_NO_WATER"
    TIER3_NO_GAS = "TIER3_NO_GAS"


class ActivationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ENDED = "ENDED"


class ChecklistRunStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChecklistItemKey(str, Enum):
    POWER_RESTORED = "POWER_RESTORED"
    WATER_POTABLE = "WATER_POTABLE"
    GAS_LEAK_CHECK = "GAS_LEAK_CHECK"
    FOOD_DISCARD_LOGGED = "FOOD_DISCARD_LOGGED"
    CASH_DRAWER_COUNTED = "CASH_DRAWER_COUNTED"


class ItemResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ReliefOrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PledgeStatus(str, Enum):
    PLEDGED = "PLEDGED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    COMMAND_CENTER_ADMIN = "CommandCenterAdmin"
    UNIT_MANAGER = "UnitManager"
    LOGISTICS_PLANNER = "LogisticsPlanner"
    FIELD_COORDINATOR = "FieldCoordinator"
    RELIEF_COORDINATOR = "ReliefCoordinator"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class StormEvent(TypedDict, total=False):
    id: str
    name: str
    status: str
    watch_started_at: str
    warning_count: int
    activated_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResourceStatus(TypedDict, total=False):
    power: str
    water: str
    gas: str
    payment_network: str


class Unit(TypedDict, total=False):
    id: str
    storm_event_id: str
    unit_code: str
    address: str
    menu_tier: str
    resource_status: dict
    cash_only_flag: bool
    last_shift_change_at: Optional[str]
    hours_since_shift_change: int
    lodging_fund_cents: int
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    full_name: str
    role: str
    home_unit_id: str
    is_jump_team: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    unit_id: str
    crew_member_id: str
    assigned_from: str
    assigned_until: str
    travel_origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    kind: str
    home_unit_id: str
    status: str
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssetAllocation(TypedDict, total=False):
    id: str
    asset_id: str
    unit_id: str
    status: str
    dispatched_at: Optional[str]
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LodgingBooking(TypedDict, total=False):
    id: str
    unit_id: str
    crew_assignment_id: str
    rooms: int
    nightly_rate_cents: int
    check_in: str
    check_out: str
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuActivation(TypedDict, total=False):
    id: str
    unit_id: str
    tier: str
    status: str
    activated_at: str
    ended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConditionReport(TypedDict, total=False):
    id: str
    unit_id: str
    power: str
    water: str
    gas: str
    payment_network: str
    reported_at: str
    created_at: str
    updated_at: str
    version: int


class ChecklistRun(TypedDict, total=False):
    id: str
    unit_id: str
    status: str
    submitted_at: Optional[str]
    reviewed_at: Optional[str]
    reviewed_by_user_id: Optional[str]
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only (no updated_at, no version)
class ChecklistItem(TypedDict, total=False):
    id: str
    checklist_run_id: str
    key: str
    result: str
    note: Optional[str]
    created_at: str


# Append-only: id + created_at only (no updated_at, no version)
class CashDrop(TypedDict, total=False):
    id: str
    unit_id: str
    amount_cents: int
    recorded_at: str
    shift_lead_note: str
    created_at: str


class ReliefOrg(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReliefPledge(TypedDict, total=False):
    id: str
    unit_id: str
    relief_org_id: str
    meal_count: int
    service_date: str
    served_count: int
    shortfall_meals: int
    overage_meals: int
    shortfall_penalty_cents: int
    reimbursement_cents: int
    final_reimbursement_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RunReport(TypedDict, total=False):
    generated_at: str
    units_reported: int
    pledges_finalized: int
    per_unit: list
