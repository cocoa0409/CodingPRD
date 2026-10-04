"""Domain types: entity TypedDicts, status enums, role enum for the Subscription Moviegoing API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    MEMBER_SERVICES = "MemberServices"
    MEMBER = "Member"
    THEATER_STAFF = "TheaterStaff"
    STUDIO_REP = "StudioRep"


class MemberStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    REJOIN_LOCKED = "REJOIN_LOCKED"


class BucketPosture(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class TheaterStatus(str, Enum):
    OPERATING = "OPERATING"
    DARK = "DARK"


class ShowtimeFormat(str, Enum):
    STANDARD = "STANDARD"
    IMAX = "IMAX"
    DOLBY = "DOLBY"
    THREE_D = "THREE_D"


class ShowtimeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_SALE = "ON_SALE"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    CHECKED_IN = "CHECKED_IN"
    EXPIRED = "EXPIRED"


class StrikeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVERSED = "REVERSED"


class LedgerKind(str, Enum):
    EARN_CONCESSION = "EARN_CONCESSION"
    EARN_ADMISSION = "EARN_ADMISSION"
    REDEEM = "REDEEM"
    EXPIRE = "EXPIRE"
    ADJUST = "ADJUST"


class SettlementReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"


class SettlementLineKind(str, Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    PAID = "PAID"


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    status: str
    loyalty_points_balance: int
    no_show_strikes_active: int
    suspended_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubscriptionPlan(TypedDict, total=False):
    id: str
    code: str
    tier: str
    monthly_fee_cents: int
    weekly_reservation_quota: int
    max_rollover_credits: int
    premium_format_allowed: bool
    max_future_reservations: int
    loyalty_points_multiplier_pct: int
    concession_discount_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    member_id: str
    plan_id: str
    status: str
    cycle_anchor_date: str
    current_cycle_index: int
    pause_count_in_cycle: int
    paused_at: Optional[str]
    pause_resume_at: Optional[str]
    cancelled_at: Optional[str]
    rejoin_locked_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReservationCreditBucket(TypedDict, total=False):
    id: str
    subscription_id: str
    week_index: int
    base_granted: int
    rollover_in: int
    credits_used: int
    credits_available: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Theater(TypedDict, total=False):
    id: str
    name: str
    timezone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Auditorium(TypedDict, total=False):
    id: str
    theater_id: str
    label: str
    seat_count: int
    supported_formats: List[str]
    created_at: str
    updated_at: str
    version: int


class Showtime(TypedDict, total=False):
    id: str
    auditorium_id: str
    film_title: str
    studio_code: str
    format: str
    runtime_minutes: int
    starts_at: str
    base_price_cents: int
    premium_surcharge_cents: int
    opening_weekend: bool
    subscriber_displacement_cap_pct: int
    seats_held_subscription: int
    seats_held_paid: int
    seats_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    member_id: str
    subscription_id: str
    showtime_id: str
    bucket_id: str
    seat_count: int
    is_premium_format: bool
    credit_consumed: bool
    status: str
    cancel_deadline: str
    settlement_reported: bool
    created_at: str
    updated_at: str
    version: int


class NoShowStrike(TypedDict, total=False):
    id: str
    member_id: str
    reservation_id: str
    issued_at: str
    expires_at: str
    status: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only (id + created_at only; NO updated_at / version)
class LoyaltyLedgerEntry(TypedDict, total=False):
    id: str
    member_id: str
    kind: str
    points: int
    source_id: Optional[str]
    note: Optional[str]
    created_at: str


class ConcessionPurchase(TypedDict, total=False):
    id: str
    member_id: str
    theater_id: str
    pre_discount_cents: int
    discount_cents: int
    charged_cents: int
    points_earned: int
    created_at: str
    updated_at: str
    version: int


class SettlementReport(TypedDict, total=False):
    id: str
    theater_id: str
    studio_code: str
    period_start: str
    period_end: str
    status: str
    total_admissions: int
    total_subscription_admissions: int
    total_gross_cents: int
    dispute_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only (id + created_at only; NO updated_at / version)
class SettlementLine(TypedDict, total=False):
    id: str
    report_id: str
    reservation_id: str
    showtime_id: str
    line_kind: str
    reported_value_cents: int
    created_at: str
