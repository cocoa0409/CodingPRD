"""Domain types: entity TypedDicts, status enums and the role enum.

Every entity in this API carries the standard field set (id, created_at,
updated_at, version); none is append-only.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ───────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRINT_OPERATIONS_DIRECTOR = "PrintOperationsDirector"
    DELIVERY_NETWORK_MANAGER = "DeliveryNetworkManager"
    NEWSROOM_OPERATIONS_MANAGER = "NewsroomOperationsManager"
    CUSTOMER_SERVICE = "CustomerService"
    SUBSCRIBER = "Subscriber"
    AUDITOR = "Auditor"


# ─── Status enums ────────────────────────────────────────────────────

class PressPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class AllocationMethod(str, Enum):
    PRIORITY = "PRIORITY"
    PROPORTIONAL = "PROPORTIONAL"


class PrintSiteStatus(str, Enum):
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"


class RegionStatus(str, Enum):
    ACTIVE = "active"
    CONSOLIDATED = "consolidated"


class PrintMarketStatus(str, Enum):
    ACTIVE = "active"
    CONSOLIDATION_PLANNED = "consolidation_planned"
    TRANSFER_IN_PROGRESS = "transfer_in_progress"
    WITHDRAWN = "withdrawn"


class FrequencyChangeStatus(str, Enum):
    NONE = "none"
    PROPOSED = "proposed"
    NOTICES_DISPATCHED = "notices_dispatched"
    APPLIED = "applied"
    REJECTED = "rejected"


class RouteSelectionStatus(str, Enum):
    CURRENT = "current"
    NEEDS_REASSIGNMENT = "needs_reassignment"


class SingleCopyMarketRule(str, Enum):
    NEWSSTAND = "newsstand"
    CARRIER = "carrier"


class PrintRouteStatus(str, Enum):
    ELIGIBLE = "eligible"
    COMMITTED = "committed"
    ORPHANED = "orphaned"


class EditionStatus(str, Enum):
    IN_PRODUCTION = "in_production"
    ON_TIME_DISPATCH = "on_time_dispatch"
    LATE_DISPATCH = "late_dispatch"
    DELIVERED_MARKET = "delivered_market"
    REVERTED_TO_DIGITAL = "reverted_to_digital"


class PayBasis(str, Enum):
    PER_STOP = "PER_STOP"
    PER_COPY = "PER_COPY"


class ContractorStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class DeliveryRouteStatus(str, Enum):
    PREPARED = "prepared"
    CONTRACT_ACTIVE = "contract_active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class DeliveryStopStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    TERMINATED = "terminated"


class SubscriberStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    MIGRATED = "migrated"
    CHURNED_PENDING_RETENTION = "churned_pending_retention"
    CHURNED = "churned"


class OfferStatus(str, Enum):
    NONE = "none"
    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class DeliveryStatus(str, Enum):
    NONE = "none"
    PAUSED = "paused"
    RESUMED = "resumed"
    TERMINATED = "terminated"


class OfferRecommendation(str, Enum):
    PRINT_CREDIT = "PRINT_CREDIT"
    DIGITAL_UPGRADE = "DIGITAL_UPGRADE"
    FULL_REFUND = "FULL_REFUND"


class NewsroomPositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class NewsroomChangeStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"


class TitleClosureStatus(str, Enum):
    ANNOUNCED = "announced"
    NOTICE_PUBLISHED = "notice_published"
    SUSPENDED = "suspended"
    MERGED = "merged"
    ARCHIVED = "archived"


class RetentionActionStatus(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


# ─── Entity TypedDicts (all common_fields: true) ─────────────────────

class RegionHub(TypedDict):
    id: str
    name: str
    total_newsroom_headcount: int
    max_print_tonnage_budget_cents: int
    transfer_cost_ceiling_cents: int
    min_on_time_ratio_pct: int
    press_posture: str
    legal_notice_block: bool
    unassigned_headcount: int
    created_at: str
    updated_at: str
    version: int


class Region(TypedDict):
    id: str
    region_hub_id: str
    name: str
    daily_headcount_floor: int
    daily_headcount_cap: int
    allocation_priority: int
    region_need_score: float
    guaranteed_headcount: int
    allocated_newsroom_headcount: int
    member_market_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrintSite(TypedDict):
    id: str
    print_site_hub_id: str
    code: str
    press_units: int
    shifts_per_night: int
    copies_per_hour_per_press: int
    distinct_shifts_per_night: int
    loading_slot_minutes: int
    max_concurrent_departures: int
    allocation_method: str
    capacity_copies: int
    allocated_copies: int
    capacity_remaining_copies: int
    annualized_savings_cents: float
    realized_savings_cents: float
    savings_divergence_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PrintMarket(TypedDict):
    id: str
    region_id: str
    name: str
    publication_deadline_utc: str
    on_time_margin_minutes: int
    per_copy_revenue_cents: int
    daily_route_cost_ceiling_cents: int
    weighted_demand_units: int
    print_edition_per_week: int
    guaranteed_floor_copies: int
    selected_print_route_id: Optional[str]
    replacement_route_id: Optional[str]
    print_site_transfer_cost_cents: float
    print_site_transfer_credit_cents: float
    net_print_site_transfer_cost_cents: float
    route_selection_status: str
    delivery_boycott_active: bool
    transfer_cost_disputed: bool
    target_print_edition_per_week: Optional[int]
    notices_dispatched_at: Optional[str]
    renewals_accepted_count: int
    single_copy_market_rule: str
    newsstand_contribution_cents: float
    carrier_contribution_cents: float
    keeps_print_single_copy: bool
    status: str
    frequency_change_status: str
    created_at: str
    updated_at: str
    version: int


class PrintRoute(TypedDict):
    id: str
    origin_print_site_id: str
    destination_market_id: str
    transit_minutes: int
    buffer_minutes: int
    dispatch_cutoff_utc: str
    is_direct_hop: bool
    distance_miles: float
    marginal_mileage_cost: float
    stops_per_night: int
    total_copies_allocated: int
    route_transport_cost: float
    marginal_cost_per_copy_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LatestEdition(TypedDict):
    id: str
    print_market_id: str
    assigned_print_site_id: Optional[str]
    slug: str
    page_count: int
    requested_print_run_copies: int
    allocated_print_run_copies: int
    press_run_hours: float
    press_ready_utc: Optional[str]
    latest_edition_ready_utc: Optional[str]
    minutes_late: int
    late_edition_penalty_cents: int
    is_on_time: bool
    late_sports_engineering_flag: bool
    legal_notice_count: int
    correction_open: bool
    correction_redispatch_cost_cents: Optional[float]
    next_edition_slot_taken: int
    second_edition_slot_open: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryContractor(TypedDict):
    id: str
    contractor_hub_id: str
    name: str
    pay_basis: str
    per_copy_rate_cents: int
    min_stop_guarantee: int
    net_60_available: bool
    cost_per_copy_ceiling_cents: int
    last_load_claim_weight_lbs: int
    sanction_reason_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict):
    id: str
    delivery_contractor_id: str
    print_market_id: str
    route_code: str
    stop_capacity: int
    per_stop_fee_cents: int
    dist_per_stop_miles: float
    cost_per_copy_ceiling_cents: int
    printed_copies_surcharge_cents: int
    cost_run_date: str
    base_cost_cents: float
    last_cost_run_date: Optional[str]
    printed_copies_last_run: int
    copy_volume_tier_pct: float
    contractor_status_factor: float
    copies_carried_night: int
    route_night_cost: float
    cost_per_copy_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryStop(TypedDict):
    id: str
    delivery_route_id: str
    print_market_id: str
    stop_code: str
    contracted_daily_copies: int
    contracted_daily_fee_cents: int
    pause_start_date: Optional[str]
    pause_end_date: Optional[str]
    pause_window_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriberContract(TypedDict):
    id: str
    delivery_stop_id: str
    subscriber_ref: str
    remaining_print_issues: int
    paid_through_utc: str
    print_issue_value_cents: int
    migration_credit_cents: int
    churn_retention_credit_cents: int
    offer_recommendation: str
    status: str
    offer_status: str
    delivery_status: str
    created_at: str
    updated_at: str
    version: int


class NewsroomPosition(TypedDict):
    id: str
    region_id: str
    role_code: str
    expertise_code: str
    monthly_cost_cents: int
    allocated_headcount: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NewsroomChange(TypedDict):
    id: str
    newsroom_position_id: str
    to_region_id: str
    from_region_id: str
    effective_date: str
    layoff_order_index: int
    requested_slots: int
    allocated_slots: int
    residual_headcount: int
    severance_cost_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TitleClosure(TypedDict):
    id: str
    title_hub_id: str
    title_code: str
    archive_retention_years: int
    digital_replacement_url: str
    archive_handoff_checksum: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RetentionAction(TypedDict):
    id: str
    subscriber_contract_id: str
    retention_offer_code: str
    retention_credit_cents: int
    cooling_off_expires_utc: str
    eligibility_policy_id: str
    status: str
    created_at: str
    updated_at: str
    version: int