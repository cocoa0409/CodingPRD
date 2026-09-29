"""Declared enum members and the pinned numeric constants of the PRD."""

from decimal import Decimal

# ---- MeetingPlanner -------------------------------------------------------
ENGAGEMENT_STATUSES = ("PROSPECT", "ENGAGED")
TIERS = ("TIER_A", "TIER_B", "TIER_C")

# ---- Hotel ----------------------------------------------------------------
PARTICIPATION_STATUSES = ("PARTICIPATING", "SUSPENDED")

# ---- CenterHall -----------------------------------------------------------
HALL_STATUSES = ("AVAILABLE", "UNDER_RENOVATION")

# ---- Opportunity ----------------------------------------------------------
SALES_STAGES = ("LEAD", "QUALIFIED", "BIDDING", "DEFINITE", "SERVICED", "LOST")
HOLD_POSTURES = ("NONE", "TENTATIVE", "CHALLENGED", "CONFIRMED", "RELEASED")
LOST_REASONS = (
    "RATE_TOO_HIGH",
    "DATES_UNAVAILABLE",
    "SPACE_UNAVAILABLE",
    "LOST_TO_COMPETITOR",
    "PLANNER_DECLINED_BID",
    "INSUFFICIENT_INCENTIVE",
    "REVISION_LIMIT_REACHED",
)

# ---- SpaceHold ------------------------------------------------------------
HOLD_STATUSES = ("HELD", "CHALLENGED", "CONFIRMED", "RELEASED", "EXPIRED")
HOLD_RANKS = ("FIRST", "SECOND")
RELEASE_REASONS = (
    "SCHEDULER_RELEASE",
    "CHALLENGE_LAPSED",
    "OPPORTUNITY_LOST",
    "SUPERSEDED_BY_CONFIRMED",
    "HOLD_EXPIRED",
    "EVENT_SERVICED",
)
ACTIVE_HOLD_STATUSES = ("HELD", "CHALLENGED")

# ---- RoomBlockCommitment --------------------------------------------------
COMMITMENT_STATUSES = ("INVITED", "OFFERED", "COMMITTED", "WITHDRAWN", "RELEASED")
LIVE_COMMITMENT_STATUSES = ("INVITED", "OFFERED", "COMMITTED")
WITHDRAW_REASONS = (
    "PROPERTY_SOLD_OUT",
    "RATE_DISPUTE",
    "INVITE_DECLINED",
    "OPPORTUNITY_LOST",
    "EVENT_SERVICED",
)

# ---- BidPackage -----------------------------------------------------------
BID_STATUSES = (
    "DRAFT",
    "INCENTIVE_PENDING",
    "APPROVED",
    "SUBMITTED",
    "ACCEPTED",
    "DECLINED",
)
LIVE_BID_STATUSES = ("DRAFT", "INCENTIVE_PENDING", "APPROVED", "SUBMITTED")
CHARGED_BID_STATUSES = ("APPROVED", "SUBMITTED", "ACCEPTED")
PLANNER_RESPONSES = ("ACCEPTED", "DECLINED", "REVISION_REQUESTED")
DECLINE_REASONS = (
    "RATE_TOO_HIGH",
    "INSUFFICIENT_INCENTIVE",
    "LOST_TO_COMPETITOR",
    "REVISION_LIMIT_REACHED",
)
LETTER_TYPES = ("MAYOR", "CHAMBER", "UNIVERSITY", "INDUSTRY_PARTNER", "CONVENTION_CENTER")
SERVICE_COMMITMENT_CODES = (
    "HOUSING_BUREAU",
    "SHUTTLE_NETWORK",
    "VOLUNTEER_CORPS",
    "WELCOME_SIGNAGE",
)

# ---- IncentiveFund / IncentiveDecision ------------------------------------
FUND_POSTURES = ("OPEN", "CONSTRAINED", "EXHAUSTED")
DECISIONS = ("APPROVED", "REDUCED", "REJECTED")

# ---- EconomicImpactEstimate ----------------------------------------------
ESTIMATE_VARIANTS = ("PROVISIONAL", "FINAL")

# ---- ServicingOrder -------------------------------------------------------
SERVICING_CATEGORIES = ("HOUSING", "TRANSPORTATION", "VOLUNTEER")
SERVICING_STATUSES = ("REQUESTED", "SCHEDULED", "DELIVERED", "CANCELLED")
OPEN_SERVICING_STATUSES = ("REQUESTED", "SCHEDULED")

# ---- BoardReport ----------------------------------------------------------
REPORT_STATUSES = ("DRAFT", "PUBLISHED")

# ==========================================================================
# Pinned constants
# ==========================================================================
QUALIFY_LEAD_TIME_DAYS = 180
FIRST_HOLD_DAYS = 90
PROMOTION_HOLD_DAYS = 30
CHALLENGE_RESPONSE_DAYS = 14
DEFAULT_TURNAROUND_HOURS = 48
HALL_HOLD_LIMIT = 2

# relationship score
SCORE_POINTS_PER_DEFINITE = 12
SCORE_ROOM_NIGHTS_PER_POINT = 500
SCORE_ROOM_NIGHT_CAP = 40
SCORE_POINTS_PER_LOST = 5
SCORE_MIN = 0
SCORE_MAX = 100
TIER_A_MIN_SCORE = 60
TIER_B_MIN_SCORE = 30
ROLLING_WINDOW_DAYS = 730

# economic impact
DELEGATE_DAILY_SPEND = Decimal("285.00")
EXHIBITOR_SPEND_PER_SQFT = Decimal("4.75")
OCCUPANCY_PERSONS_PER_ROOM = Decimal("1.6")
INDIRECT_MULTIPLIER = Decimal("1.65")
LODGING_TAX_RATE = Decimal("0.15")

# incentive cap band ladder (marginal)
BAND_1_ROOM_NIGHTS = 5000
BAND_1_RATE = Decimal("12.00")
BAND_2_ROOM_NIGHTS = 10000
BAND_2_RATE = Decimal("8.00")
BAND_3_RATE = Decimal("5.00")

TIER_YIELD_RATES = {
    "TIER_A": Decimal("0.35"),
    "TIER_B": Decimal("0.25"),
    "TIER_C": Decimal("0.15"),
}

COVERAGE_FACTOR_FULL = Decimal("1.00")
COVERAGE_FACTOR_MID = Decimal("0.90")
COVERAGE_FACTOR_LOW = Decimal("0.75")
COVERAGE_FULL_THRESHOLD = Decimal("95.00")
COVERAGE_MID_THRESHOLD = Decimal("85.00")

# admin fee bands, selected from the gross figure only
FEE_BAND_1_CEILING = Decimal("100000.00")
FEE_BAND_1_RATE = Decimal("0.05")
FEE_BAND_2_CEILING = Decimal("250000.00")
FEE_BAND_2_RATE = Decimal("0.04")
FEE_BAND_3_RATE = Decimal("0.03")

TAX_PAYBACK_FLOOR = Decimal("3.00")

# fund posture
FUND_CONSTRAINED_FRACTION = Decimal("0.10")

# submission gates
BLOCK_COVERAGE_FLOOR = Decimal("85.00")
CUTOFF_SPREAD_TOLERANCE_DAYS = 2
SUPPORT_LETTER_TYPE_MINIMUM = 2
MAX_BID_ROUNDS = 3

# attrition
ATTRITION_ALLOWANCE_FRACTION = Decimal("0.80")
ATTRITION_DAMAGE_RATE = Decimal("0.75")
