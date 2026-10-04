"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class ClubStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BillingPolicy(str, Enum):
    SCHEDULE = "SCHEDULE"
    ACTUAL = "ACTUAL"


class TierCode(str, Enum):
    CLASSIC = "CLASSIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    LAPSED = "LAPSED"
    REINSTATED = "REINSTATED"
    CANCELLED = "CANCELLED"


class HouseholdMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class Relationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"
    OTHER = "OTHER"


class MembershipEventType(str, Enum):
    ENROLLMENT = "ENROLLMENT"
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"
    RENEWAL = "RENEWAL"
    LAPSE = "LAPSE"
    REINSTATEMENT = "REINSTATEMENT"
    CANCELLATION = "CANCELLATION"
    WAITING_PERIOD_SATISFIED = "WAITING_PERIOD_SATISFIED"


class ProviderKind(str, Enum):
    OWNED = "OWNED"
    CONTRACTED = "CONTRACTED"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ServiceType(str, Enum):
    TOW = "TOW"
    BATTERY = "BATTERY"
    LOCKOUT = "LOCKOUT"
    TIRE = "TIRE"
    FUEL = "FUEL"
    WINCH = "WINCH"


class ServiceCallStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    EN_ROUTE = "EN_ROUTE"
    ON_SCENE = "ON_SCENE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CancelReason(str, Enum):
    NONE = "NONE"
    MEMBER_REQUEST = "MEMBER_REQUEST"
    NO_PROVIDER = "NO_PROVIDER"
    DUPLICATE = "DUPLICATE"


class DispatchStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FailureReason(str, Enum):
    NONE = "NONE"
    PROVIDER_DECLINED = "PROVIDER_DECLINED"
    NO_PARTS = "NO_PARTS"
    MEMBER_NO_SHOW = "MEMBER_NO_SHOW"


class SettlementPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ASSESSED = "ASSESSED"


class SettlementLineStatus(str, Enum):
    PENDING = "PENDING"
    SWEPT = "SWEPT"
    ASSESSED = "ASSESSED"
    REVERSED = "REVERSED"


class ProductType(str, Enum):
    TRAVEL_AGENCY = "TRAVEL_AGENCY"
    INSURANCE_AGENCY = "INSURANCE_AGENCY"
    IDENTITY_PROTECTION = "IDENTITY_PROTECTION"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SaleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REFUNDED = "REFUNDED"


class PartKind(str, Enum):
    BATTERY = "BATTERY"
    TIRE = "TIRE"
    FUEL_CAN = "FUEL_CAN"
    LOCKSMITH_KIT = "LOCKSMITH_KIT"


class UserRole(str, Enum):
    CLUB_ADMIN = "ClubAdmin"
    MEMBER_SERVICES_REP = "MemberServicesRep"
    DISPATCHER = "Dispatcher"
    PROVIDER_OPS = "ProviderOps"
    SETTLEMENT_CLERK = "SettlementClerk"
    FEDERATION_FINANCE = "FederationFinance"
    AGENT = "Agent"


class Club(TypedDict, total=False):
    id: str
    club_code: str
    name: str
    territory_state_codes: List[str]
    default_arrival_target_minutes: int
    billing_policy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MembershipTier(TypedDict, total=False):
    id: str
    code: str
    annual_dues_cents: int
    included_tow_miles: int
    annual_call_cap: int
    lockout_benefit_cents: int
    battery_service_included: bool
    household_member_price_cents: int
    overage_rate_cents_per_mile: int
    upgrade_waiting_days: int
    rank: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict, total=False):
    id: str
    home_club_id: str
    primary_member_name: str
    primary_member_email: str
    tier_code: str
    status: str
    enrolled_at: str
    term_start_date: str
    term_end_date: str
    lapse_at: Optional[str]
    reinstatement_count: int
    calls_used_current_term: int
    account_credit_cents: int
    tier_upgrade_effective_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HouseholdMember(TypedDict, total=False):
    id: str
    membership_id: str
    full_name: str
    relationship: str
    is_primary: bool
    date_of_birth: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Audit entity: immutable after creation — carries ONLY id + created_at
# (no updated_at, no version), per PRD §2.5.
class MembershipEvent(TypedDict, total=False):
    id: str
    created_at: str
    membership_id: str
    event_type: str
    from_tier: Optional[str]
    to_tier: Optional[str]
    effective_at: str
    note: str


class ServiceProvider(TypedDict, total=False):
    id: str
    servicing_club_id: str
    name: str
    provider_kind: str
    capabilities: List[str]
    home_base_state_code: str
    sla_multiplier: float
    shift_start_minute: int
    shift_end_minute: int
    max_concurrent_dispatches: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TruckPartStock(TypedDict, total=False):
    id: str
    provider_id: str
    part_sku: str
    part_kind: str
    quantity_on_hand: int
    reorder_level: int
    created_at: str
    updated_at: str
    version: int


class ServiceCall(TypedDict, total=False):
    id: str
    membership_id: str
    requesting_member_id: str
    service_type: str
    breakdown_location_state: str
    servicing_club_id: str
    is_pre_existing_need: bool
    benefit_tier_code: str
    requested_tow_miles: int
    benefit_eligible: bool
    status: str
    cancel_reason: str
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict, total=False):
    id: str
    service_call_id: str
    provider_id: str
    sequence_number: int
    assigned_at: str
    promised_arrive_by: str
    arrived_at: Optional[str]
    completed_at: Optional[str]
    sla_met: Optional[bool]
    dispatched_tow_miles: int
    provisional_mileage_charge_cents: int
    actual_tow_miles: int
    parts_used: List[Dict[str, Any]]
    parts_charge_cents: int
    mileage_charge_cents: int
    total_member_charge_cents: int
    status: str
    failure_reason: str
    created_at: str
    updated_at: str
    version: int


class SettlementPeriod(TypedDict, total=False):
    id: str
    servicing_club_id: str
    period_start_date: str
    period_end_date: str
    status: str
    closed_by: str
    total_foreign_call_count: int
    total_gross_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementLine(TypedDict, total=False):
    id: str
    settlement_period_id: Optional[str]
    service_call_id: str
    home_club_id: str
    servicing_club_id: str
    gross_amount_cents: int
    excluded: bool
    exclusion_reason: str
    assessed_fee_cents: int
    assessed_net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AncillaryProduct(TypedDict, total=False):
    id: str
    product_type: str
    name: str
    price_cents: int
    min_tier_code: str
    commission_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AncillarySale(TypedDict, total=False):
    id: str
    membership_id: str
    product_id: str
    sold_by_agent_id: str
    price_cents: int
    commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
