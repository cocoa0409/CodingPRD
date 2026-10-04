"""Domain types for the driver-incentives API: status enums and entity shapes."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INCENTIVE_OPS = "IncentiveOps"
    PAYMENTS_OFFICER = "PaymentsOfficer"
    FRAUD_ANALYST = "FraudAnalyst"
    DRIVER = "Driver"


# --------------------------------------------------------------------------
# Enumerated domain values
# --------------------------------------------------------------------------
class MarketStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class RatePosture(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    PROBATION = "PROBATION"
    INELIGIBLE = "INELIGIBLE"


class FraudPosture(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"


class ProgramType(str, Enum):
    STREAK = "STREAK"
    BONUS_ZONE = "BONUS_ZONE"
    CHALLENGE = "CHALLENGE"
    GUARANTEE = "GUARANTEE"


class StackingClass(str, Enum):
    STACKABLE = "STACKABLE"
    EXCLUSIVE = "EXCLUSIVE"


class RideType(str, Enum):
    STANDARD = "STANDARD"
    SHARED = "SHARED"
    SCHEDULED = "SCHEDULED"
    LUX = "LUX"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class RideStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    DRIVER_CANCELLED = "DRIVER_CANCELLED"
    RIDER_CANCELLED = "RIDER_CANCELLED"
    DECLINED = "DECLINED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VOIDED = "VOIDED"


class CancelledBy(str, Enum):
    DRIVER = "DRIVER"
    RIDER = "RIDER"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    REOPENED = "REOPENED"
    VOID = "VOID"


class BasisVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DISPUTED = "DISPUTED"
    AMENDED = "AMENDED"


class AppealSubjectType(str, Enum):
    ELIGIBILITY = "ELIGIBILITY"
    STATEMENT = "STATEMENT"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO = "MORE_INFO"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_OVERTURNED = "RESOLVED_OVERTURNED"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"


class AppealOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class FraudSignalType(str, Enum):
    INFLATED_RIDE = "INFLATED_RIDE"
    COLLUSION = "COLLUSION"
    LOCATION_SPOOF = "LOCATION_SPOOF"


class FraudFlagStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class SupplyShortfallStatus(str, Enum):
    OPEN = "OPEN"
    ADDRESSED = "ADDRESSED"
    EXPIRED = "EXPIRED"


class CostForecastStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------
# Entity shapes (PRD §2.4: id + created_at + updated_at + version on every
# primary entity).
# --------------------------------------------------------------------------
class Market(TypedDict):
    id: str
    market_code: str
    geo_cells: List[str]
    incentive_budget_cents: int
    budget_spent_cents: int
    budget_reserved_cents: int
    budget_available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    market_id: str
    display_name: str
    rate_posture: str
    fraud_posture: str
    acceptance_rate_bps: int
    cancellation_rate_bps: int
    offers_total: int
    accepted_total: int
    cancelled_total: int
    account_status: str
    created_at: str
    updated_at: str
    version: int


class IncentiveProgram(TypedDict):
    id: str
    market_id: str
    program_type: str
    title: str
    window_start_utc: str
    window_end_utc: str
    geo_cell_id: Optional[str]
    stacking_class: str
    excluded_ride_types: List[str]
    streak_length: Optional[int]
    streak_payout_cents: Optional[int]
    zone_multiplier_bps: Optional[int]
    challenge_ride_target: Optional[int]
    challenge_payout_cents: Optional[int]
    guaranteed_weekly_cents: Optional[int]
    guaranteed_min_rides: Optional[int]
    promised_make_up_max_cents: int
    capacity: Optional[int]
    status: str
    forecast_headroom_cents: int
    created_at: str
    updated_at: str
    version: int


class Ride(TypedDict):
    id: str
    driver_id: str
    market_id: str
    ride_type: str
    geo_cell_id: str
    base_fare_cents: int
    tips_cents: int
    request_offer_recorded: bool
    status: str
    qualifying_earnings_cents: int
    created_at: str
    updated_at: str
    version: int


class IncentiveEnrollment(TypedDict):
    id: str
    driver_id: str
    program_id: str
    status: str
    progress_count: int
    streak_broken: bool
    payout_cents: int
    earned_qualifying_cents: int
    created_at: str
    updated_at: str
    version: int


class GuaranteeSettlement(TypedDict):
    id: str
    driver_id: str
    program_id: str
    week_start_utc: str
    promised_cents: int
    actual_gross_cents: int
    qualifying_ride_count: int
    make_up_cents: int
    basis_variant: str
    status: str
    paid_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EarningsStatement(TypedDict):
    id: str
    driver_id: str
    week_start_utc: str
    base_fares_cents: int
    tips_cents_total: int
    bonus_total_cents: int
    make_up_total_cents: int
    adjustments_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    driver_id: str
    subject_type: str
    statement_id: Optional[str]
    reason: str
    round_count: int
    status: str
    adjustment_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FraudFlag(TypedDict):
    id: str
    driver_id: str
    ride_id: str
    ring_id: Optional[str]
    signal_type: str
    acute_score: int
    chronic_score: int
    severity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyShortfall(TypedDict):
    id: str
    market_id: str
    geo_cell_id: str
    hour_bucket: int
    severity_bps: int
    recommended_bonus_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CostForecast(TypedDict):
    id: str
    program_id: str
    baseline_rides: int
    lift_bps: int
    cannibalization_bps: int
    projected_incremental_rides: int
    projected_cannibalized_rides: int
    projected_cost_cents: int
    forecast_revision: int
    status: str
    created_at: str
    updated_at: str
    version: int
