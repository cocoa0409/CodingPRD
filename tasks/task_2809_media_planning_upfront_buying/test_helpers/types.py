"""Vocabularies and resource shapes of the Media Planning & Upfront Buying API.

The enumerations mirror the declared value sets exactly, so a test never spells
an enum member as a bare string.  The ``TypedDict`` shapes name every field a
resource carries; the two append-only records carry an identifier and a creation
instant only, so their shapes deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ==========================================================================
# Acting roles
# ==========================================================================
class UserRole(str, Enum):
    AGENCY_PLANNER = "AgencyPlanner"
    AGENCY_BUYER = "AgencyBuyer"
    AGENCY_CONTROLLER = "AgencyController"
    SELLER_REP = "SellerRep"
    ADVERTISER_CLIENT = "AdvertiserClient"
    MEASUREMENT_PROVIDER = "MeasurementProvider"


# ==========================================================================
# Marketplace vocabularies
# ==========================================================================
class Channel(str, Enum):
    LINEAR_TV = "LINEAR_TV"
    CTV = "CTV"
    DIGITAL_VIDEO = "DIGITAL_VIDEO"
    AUDIO = "AUDIO"


class Platform(str, Enum):
    LINEAR = "LINEAR"
    CTV = "CTV"
    DIGITAL = "DIGITAL"
    AUDIO = "AUDIO"


class Market(str, Enum):
    UPFRONT = "UPFRONT"
    SCATTER = "SCATTER"


class Daypart(str, Enum):
    PRIME = "PRIME"
    DAYTIME = "DAYTIME"
    LATE = "LATE"
    DIGITAL_ANY = "DIGITAL_ANY"


class CategoryCode(str, Enum):
    BEVERAGE = "BEVERAGE"
    AUTOMOTIVE = "AUTOMOTIVE"
    PHARMA = "PHARMA"
    RETAIL = "RETAIL"
    FINANCE = "FINANCE"
    TELECOM = "TELECOM"
    GROCERY = "GROCERY"
    INSURANCE = "INSURANCE"
    TRAVEL = "TRAVEL"
    BEAUTY = "BEAUTY"
    FITNESS = "FITNESS"
    TECHNOLOGY = "TECHNOLOGY"
    HOME = "HOME"
    ELECTRONICS = "ELECTRONICS"


class MeasurementBasis(str, Enum):
    LINEAR_C3 = "LINEAR_C3"
    DIGITAL_VAST = "DIGITAL_VAST"
    CTV_SERVER = "CTV_SERVER"


class ExclusivityMode(str, Enum):
    SHARED = "SHARED"
    EXCLUSIVE = "EXCLUSIVE"


class MakeGoodProvision(str, Enum):
    MAKE_GOOD_UNITS = "MAKE_GOOD_UNITS"
    CASH_CREDIT = "CASH_CREDIT"
    NONE = "NONE"


class OfferActor(str, Enum):
    AGENCY = "AGENCY"
    SELLER = "SELLER"


class RightsKind(str, Enum):
    OPTION_ROLL = "OPTION_ROLL"
    CANCELLATION = "CANCELLATION"


class DedupMethod(str, Enum):
    SEQUENTIAL_DEDUP = "SEQUENTIAL_DEDUP"
    AGGREGATE_DEDUP = "AGGREGATE_DEDUP"


class AiringOutcome(str, Enum):
    AIRED = "AIRED"
    PREEMPTED = "PREEMPTED"


class ReconciliationGroup(str, Enum):
    LINEAR = "LINEAR"
    CTV = "CTV"
    DIGITAL = "DIGITAL"


# ==========================================================================
# State vocabularies
# ==========================================================================
class CreditStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WATCH = "WATCH"
    HOLD = "HOLD"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CLIENT_APPROVAL = "PENDING_CLIENT_APPROVAL"
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FUNDED = "FUNDED"


class PlanPosture(str, Enum):
    WITHIN_PLAN = "WITHIN_PLAN"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"


class AllocationStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"


class AllocationPosture(str, Enum):
    WITHIN_PLAN = "WITHIN_PLAN"
    OVERCOMMITTED = "OVERCOMMITTED"


class ForecastStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    EXHAUSTED = "EXHAUSTED"


class NegotiationStatus(str, Enum):
    AGENCY_OFFER = "AGENCY_OFFER"
    SELLER_COUNTER = "SELLER_COUNTER"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"


class BuyStatus(str, Enum):
    PENDING_PLACEMENT = "PENDING_PLACEMENT"
    PLACED = "PLACED"
    IN_FLIGHT = "IN_FLIGHT"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class StewardshipStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    UNDER_DELIVERED = "UNDER_DELIVERED"
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    MADE_GOOD = "MADE_GOOD"


class SettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    CLIENT_PAID = "CLIENT_PAID"
    REMITTED = "REMITTED"


class UnitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AIRED = "AIRED"
    PREEMPTED = "PREEMPTED"
    CANCELLED = "CANCELLED"
    MAKE_GOOD_SCHEDULED = "MAKE_GOOD_SCHEDULED"
    MAKE_GOOD_AIRED = "MAKE_GOOD_AIRED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"


class MakeGoodStatus(str, Enum):
    OPEN = "OPEN"
    OFFERED = "OFFERED"
    SCHEDULED = "SCHEDULED"
    WAIVED = "WAIVED"


class InvoiceClientStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class InvoiceSellerStatus(str, Enum):
    UNREMITTED = "UNREMITTED"
    PARTIALLY_REMITTED = "PARTIALLY_REMITTED"
    REMITTED = "REMITTED"


class RunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    COMPLETED_NO_DATA = "COMPLETED_NO_DATA"


# ==========================================================================
# Common system fields
# ==========================================================================
class Timestamped(TypedDict):
    """The identity and audit fields every mutable resource carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyRecord(TypedDict):
    """The identity fields an append-only record carries: no update, no version."""

    id: str
    created_at: str


# ==========================================================================
# Resource shapes
# ==========================================================================
class Advertiser(Timestamped):
    name: str
    category_code: str
    payment_terms_days: int
    sequential_liability_enabled: bool
    credit_limit_cents: int
    credit_status: str
    late_payment_count: int
    outstanding_receivable_cents: int


class Campaign(Timestamped):
    advertiser_id: str
    name: str
    target_demo: str
    universe_thousands: int
    reach_goal_pct: float
    frequency_goal: float
    total_budget_cents: int
    flight_start: str
    flight_end: str
    fiscal_quarter: str
    plan_status: str
    funding_status: str
    plan_posture: str
    funded_cents: int
    allocated_budget_cents: int
    unallocated_budget_cents: int
    committed_gross_cents: int
    uncommitted_budget_cents: int
    planned_impressions_total: int
    planned_grp_total: float


class ChannelAllocation(Timestamped):
    campaign_id: str
    channel: str
    allocation_pct: float
    planned_cpm_cents: int
    planned_market: str
    primary_daypart: str
    allocated_cents: int
    effective_planned_cpm_cents: int
    planned_impressions: int
    planned_grp: float
    planned_frequency: float
    committed_cents: int
    posture: str
    status: str


class Seller(Timestamped):
    name: str
    platform_types: List[str]
    make_good_capacity_impressions: int
    open_make_good_impressions: int
    scheduled_make_good_impressions: int


class InventoryForecast(Timestamped):
    seller_id: str
    market: str
    fiscal_quarter: str
    daypart: str
    program: str
    platform: str
    window_start: str
    window_end: str
    total_impressions: int
    available_impressions: int
    forecast_cpm_cents: int
    exclusivity_mode: str
    status: str


class Negotiation(Timestamped):
    campaign_id: str
    seller_id: str
    channel_allocation_id: str
    market: str
    channel: str
    requested_impressions: int
    opening_cpm_cents: int
    guarantee_pct: float
    make_good_provision: str
    option_pct_ceiling: float
    current_cpm_cents: int
    current_impressions: int
    round_number: int
    last_offer_actor: str
    status: str
    accepted_cpm_cents: Optional[int]
    accepted_impressions: Optional[int]


class Buy(Timestamped):
    campaign_id: str
    seller_id: str
    negotiation_id: str
    channel_allocation_id: str
    market: str
    channel: str
    guaranteed_impressions: int
    agreed_cpm_cents: int
    net_media_cost_cents: int
    commission_rate: float
    agency_commission_cents: int
    gross_cost_cents: int
    placed_impressions: int
    credited_impressions_provisional: int
    credited_impressions_final: int
    provisional_delivery_index: float
    final_delivery_index: float
    open_shortfall_impressions: int
    made_good_impressions: int
    waived_impressions: int
    buy_status: str
    stewardship_status: str
    settlement_status: str
    flight_start: str
    flight_end: str
    option_window_close: str
    cancel_window_1_close: str
    cancel_window_2_close: str
    option_pct_ceiling: float
    cancelled_pct_cumulative: float
    option_pct_cumulative: float
    make_good_provision: str
    placed_by_user_id: Optional[str]


class BuyUnit(Timestamped):
    buy_id: str
    forecast_id: str
    make_good_id: Optional[str]
    daypart: str
    program: str
    platform: str
    units: int
    unit_rate_cents: int
    projected_impressions: int
    actual_impressions: int
    air_window_start: str
    air_window_end: str
    exclusive: bool
    line_net_cents: int
    line_commission_cents: int
    line_gross_cents: int
    status: str


class DeliveryReport(Timestamped):
    buy_id: str
    measurement_basis: str
    period_start: str
    period_end: str
    delivered_impressions: int
    delivered_demo_impressions: int
    is_post_buy_final: bool
    dispute_reason: Optional[str]
    status: str


class MakeGood(Timestamped):
    buy_id: str
    offered_forecast_id: Optional[str]
    shortfall_impressions: int
    shortfall_value_cents: int
    offered_impressions: int
    offered_window_start: Optional[str]
    offered_window_end: Optional[str]
    offer_round: int
    rejection_reason: Optional[str]
    waived_credit_cents: int
    status: str


class RightsExercise(AppendOnlyRecord):
    buy_id: str
    kind: str
    requested_pct: float
    applied_ceiling_pct: float
    delta_impressions: int
    delta_gross_cents: int
    cancelled_unit_count: int
    exercised_at: str
    exercised_by_user_id: str


class ReconciliationRun(AppendOnlyRecord):
    campaign_id: str
    dedup_method: str
    aggregate_duplication_pct: Optional[float]
    linear_ctv_duplication_pct: Optional[float]
    ctv_digital_duplication_pct: Optional[float]
    linear_digital_duplication_pct: Optional[float]
    group_reach_pct: Dict[str, float]
    gross_reach_pct_total: float
    unduplicated_reach_pct: float
    implied_frequency: float
    included_report_count: int
    status: str
    computed_at: str


class Invoice(Timestamped):
    buy_id: str
    billing_period_start: str
    billing_period_end: str
    line_count: int
    gross_billable_cents: int
    agency_commission_cents: int
    seller_payable_cents: int
    make_good_credit_cents: int
    net_payable_cents: int
    max_remittable_cents: int
    client_paid_cents: int
    seller_remitted_cents: int
    due_date: Optional[str]
    issued_at: Optional[str]
    late_payment_flag: bool
    approver_user_id: Optional[str]
    client_status: str
    seller_status: str


#: Fields carried by every mutable resource of the domain.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

#: Fields carried by the two append-only records.
APPEND_ONLY_FIELDS = ("id", "created_at")

#: Fields an append-only record must never carry.
FORBIDDEN_ON_APPEND_ONLY = ("updated_at", "version")

#: Response envelope keys.
ENVELOPE_KEYS = ("meta", "response_type", "data")

#: Pagination keys carried by a list response's meta block.
PAGINATION_META_KEYS = ("limit", "offset", "total_count", "has_more")

Json = Dict[str, Any]
