"""Domain types for the Sports Ticket Sales Operations API.

Entity shapes, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    TICKET_OPS_ADMIN = "TicketOpsAdmin"
    REVENUE_MANAGER = "RevenueManager"
    SALES_REP = "SalesRep"
    ACCOUNT_HOLDER = "AccountHolder"


class SeasonStatus(str, Enum):
    PLANNING = "PLANNING"
    RENEWAL_OPEN = "RENEWAL_OPEN"
    GENERAL_ONSALE = "GENERAL_ONSALE"
    IN_SEASON = "IN_SEASON"
    ARCHIVED = "ARCHIVED"


class DynamicPricingMode(str, Enum):
    AGGRESSIVE = "AGGRESSIVE"
    BALANCED = "BALANCED"


class GameStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PLAYED = "PLAYED"


class OpponentTier(str, Enum):
    MARQUEE = "MARQUEE"
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    VALUE = "VALUE"


class DayBucket(str, Enum):
    WEEKEND = "WEEKEND"
    WEEKDAY = "WEEKDAY"


class SeatStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    ASSIGNED = "ASSIGNED"


class PriceZone(str, Enum):
    ZONE_A = "ZONE_A"
    ZONE_B = "ZONE_B"
    ZONE_C = "ZONE_C"
    ZONE_D = "ZONE_D"


class PlanType(str, Enum):
    FULL_SEASON = "FULL_SEASON"
    HALF_SEASON = "HALF_SEASON"
    PARTIAL = "PARTIAL"
    GROUP = "GROUP"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class RepStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"


class AccountType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"
    CORPORATE = "CORPORATE"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    LAPSED = "LAPSED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ServiceStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    CHURNED = "CHURNED"
    WON_BACK = "WON_BACK"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SCHEDULED = "SCHEDULED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    DELINQUENT = "DELINQUENT"
    REFUNDED = "REFUNDED"


class HoldType(str, Enum):
    RENEWAL_HOLD = "RENEWAL_HOLD"
    UPGRADE_HOLD = "UPGRADE_HOLD"
    GROUP_HOLD = "GROUP_HOLD"
    ORDER_HOLD = "ORDER_HOLD"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONVERTED = "CONVERTED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class PackageStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"


class TransferType(str, Enum):
    TRANSFER = "TRANSFER"
    RESALE = "RESALE"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


class Season(TypedDict):
    id: str
    code: str
    year: int
    total_home_games: int
    renewal_deadline_utc: str
    revenue_goal_cents: int
    season_status: str
    dynamic_pricing_mode: str
    revenue_goal_met: bool
    contracted_revenue_cents: int
    secondary_market_volume_cents: int
    total_seat_count: int
    available_seat_count: int
    held_seat_count: int
    assigned_seat_count: int
    renewal_opened_at_utc: Optional[str]
    last_ops_run_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Game(TypedDict):
    id: str
    season_id: str
    opponent_code: str
    opponent_tier: str
    game_date_utc: str
    day_bucket: str
    demand_index: int
    hospitality_headcount_cap: int
    game_status: str
    hospitality_booked_headcount: int
    scanned_count: int
    expected_attendance: int
    no_show_count: int
    no_show_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict):
    id: str
    season_id: str
    section_code: str
    row_label: str
    seat_number: int
    price_zone: str
    seat_status: str
    assigned_account_id: Optional[str]
    scanned_game_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class SeasonPlan(TypedDict):
    id: str
    season_id: str
    base_plan_id: Optional[str]
    plan_type: str
    game_ids: List[str]
    min_seats: int
    max_seats: int
    plan_status: str
    included_game_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceRep(TypedDict):
    id: str
    rep_name: str
    territory_code: str
    book_capacity: int
    rep_status: str
    assigned_account_count: int
    touchpoints_logged_count: int
    created_at: str
    updated_at: str
    version: int


class TicketAccount(TypedDict):
    id: str
    account_name: str
    account_type: str
    territory_code: str
    tenure_years: int
    assigned_rep_id: Optional[str]
    billing_status: str
    service_status: str
    past_due_since_utc: Optional[str]
    at_risk_since_utc: Optional[str]
    last_touchpoint_at_utc: Optional[str]
    renewal_priority_active: bool
    loyalty_credit_cents: int
    no_show_count: int
    season_no_show_count: int
    attended_count: int
    transfer_count_season: int
    churn_risk_rolling: int
    churn_risk_campaign: int
    lifetime_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    index: int
    due_date_utc: str
    amount_cents: int
    paid_cents: int


class PlanOrder(TypedDict):
    id: str
    account_id: str
    plan_id: str
    seat_ids: List[str]
    discount_pct: float
    order_status: str
    payment_status: str
    quoted_total_cents: int
    final_total_cents: int
    amount_paid_cents: int
    installment_count: Optional[int]
    installments: List[Installment]
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeatHold(TypedDict):
    id: str
    seat_id: str
    account_id: str
    origin_order_id: Optional[str]
    hold_type: str
    hold_window_start_utc: str
    hold_window_end_utc: str
    hold_status: str
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HospitalityPackage(TypedDict):
    id: str
    game_id: str
    account_id: str
    suite_code: str
    headcount: int
    service_window_start_utc: str
    service_window_end_utc: str
    package_status: str
    gross_fee_cents: int
    partner_discount_pct: float
    service_fee_cents: int
    total_due_cents: int
    created_at: str
    updated_at: str
    version: int


class TicketTransfer(TypedDict):
    id: str
    order_id: str
    game_id: str
    seat_id: str
    from_account_id: str
    to_account_id: Optional[str]
    transfer_type: str
    resale_price_cents: Optional[int]
    face_value_cents: int
    floor_price_cents: int
    credit_awarded_cents: int
    transfer_status: str
    decided_by_user_id: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
