"""Domain constants — every numeric threshold, rate table and closed enum the
PRD names, plus the pre-computed money literals for the canonical scenario.

Money is always an integer number of cents (PRD §2.6: "All monetary amounts in
this system are integers denominated in cents; no money field is ever a decimal
or a string."). Rates are basis points: "applying a rate means multiplying the
base amount by the basis-point figure and dividing the product by ten thousand".
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
# "Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z"
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_DEFAULT_MILLIS = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
ROLES = ("SpaDirector", "ComplianceOfficer", "SpaCoordinator", "Therapist", "Guest")

# ---------------------------------------------------------------------------
# Enums (PRD §3.1 - §3.9)
# ---------------------------------------------------------------------------
ROOM_CLASSES = ("DRY", "WET", "HYDRO", "COUPLES")
ROOM_STATUSES = ("ACTIVE", "MAINTENANCE", "OUT_OF_SERVICE")
SCOPE_LEVELS = ("BASIC", "ADVANCED")
SCOPE_RANK = {"BASIC": 1, "ADVANCED": 2}
EMPLOYMENT_TYPES = ("EMPLOYEE", "CONTRACTOR")
COMMISSION_TIERS = ("JUNIOR", "SENIOR", "MASTER")
THERAPIST_STATUSES = ("ACTIVE", "SUSPENDED", "INACTIVE")
SUSPENSION_REASONS = ("LICENSE_EXPIRED", "DIRECTOR_ACTION")
LICENSE_TYPES = ("LMT", "ESTHETICIAN", "NAIL_TECH")
VERIFICATION_STATUSES = ("PENDING_REVIEW", "VERIFIED", "REJECTED", "EXPIRED")
REVIEW_DECISIONS = ("VERIFIED", "REJECTED")
CE_CATEGORIES = ("ETHICS", "CLINICAL", "SAFETY")
CE_VARIANTS = ("CALENDAR_WINDOW", "ROLLING_24M")
GRANT_STATUSES = ("ACTIVE", "LAPSED", "REVOKED")
BLOCK_TYPES = ("AVAILABLE", "BREAK", "ADMIN")
LOYALTY_TIERS = ("NONE", "SILVER", "GOLD", "PLATINUM")
BOOKING_PRIVILEGES = ("OPEN", "RESTRICTED")
INTAKE_STATUSES = (
    "DRAFT", "SUBMITTED", "SCREENED_CLEAR", "SCREENED_FLAGGED",
    "OVERRIDDEN", "SUPERSEDED",
)
SCHEDULE_STATUSES = (
    "REQUESTED", "CONFIRMED", "CHECKED_IN", "IN_SERVICE", "COMPLETED",
    "CANCELLED", "LATE_CANCELLED", "NO_SHOW",
)
TERMINAL_SCHEDULE_STATUSES = ("COMPLETED", "CANCELLED", "LATE_CANCELLED", "NO_SHOW")
CLEARANCE_STATUSES = ("PENDING", "CLEARED", "BLOCKED")
# PRD §2.10: "set from the first failing clause in that order"
CLEARANCE_BLOCK_REASONS = (
    "INTAKE_FLAGGED", "LICENSE_INVALID", "THERAPIST_SUSPENDED", "ROOM_UNAVAILABLE",
)
ASSIGNMENT_MODES = ("EXPLICIT", "AUTO")
ATTACHMENT_STATUSES = ("RECOMMENDED", "PURCHASED", "DECLINED", "EXPIRED")
ATTACHMENT_OUTCOMES = ("PURCHASED", "DECLINED")
SETTLEMENT_VARIANTS = ("PROVISIONAL", "FINAL")
SETTLEMENT_STATUSES = ("PROVISIONAL", "SUPERSEDED", "FINALIZED", "REVERSED")
FOLIO_KINDS = (
    "TREATMENT", "RETAIL", "SETTLEMENT_ADJUSTMENT", "REVERSAL",
    "LATE_CANCEL", "NO_SHOW",
)

# PRD §3.4: closed literal registry of five high-risk codes
HIGH_RISK_CONDITION_CODES = (
    "ACUTE_HYPERTENSION",
    "PREGNANCY_FIRST_TRIMESTER",
    "DEEP_VEIN_THROMBOSIS",
    "RECENT_SURGERY_90D",
    "ACTIVE_INFECTION",
)

# ---------------------------------------------------------------------------
# Treatment menu / room shape limits (PRD §3.1)
# ---------------------------------------------------------------------------
DURATION_MIN_MINUTES = 15
DURATION_MAX_MINUTES = 240
DURATION_GRAIN_MINUTES = 15
CODE_MAX_LENGTH = 24
SKILL_CODE_MAX_LENGTH = 32
CAPACITY_GUESTS_VALUES = (1, 2)
TURNOVER_BUFFER_MIN = 0
TURNOVER_BUFFER_MAX = 60
ACTUAL_DURATION_MIN = 1
ACTUAL_DURATION_MAX = 480

# ---------------------------------------------------------------------------
# Price quote (PRD §3.5)
# ---------------------------------------------------------------------------
ROOM_CLASS_MULTIPLIER_BP = {"DRY": 10000, "WET": 11500, "HYDRO": 13000, "COUPLES": 12500}
PEAK_SURCHARGE_BP = 1500
PEAK_HOUR_START_UTC = 16
PEAK_HOUR_END_UTC = 20
HIGH_DEMAND_SURCHARGE_BP = 1000
SURCHARGE_CAP_BP = 2000
LOYALTY_DISCOUNT_BP = {"NONE": 0, "SILVER": 500, "GOLD": 1000, "PLATINUM": 1500}
MAX_DISCOUNT_CENTS = 4000
PRICE_FLOOR_BP = 8000

# ---------------------------------------------------------------------------
# Settlement waterfall (PRD §3.9)
# ---------------------------------------------------------------------------
GRATUITY_CAP_BP = 5000
OVERTIME_GRACE_MINUTES = 5
OVERTIME_BLOCK_MINUTES = 15
OVERTIME_BLOCK_CENTS = 2500
SHORTFALL_GRACE_MINUTES = 5
SERVICE_CHARGE_TIER_THRESHOLD_CENTS = 50000
SERVICE_CHARGE_STANDARD_BP = 1800
SERVICE_CHARGE_REDUCED_BP = 1500
THERAPIST_SHARE_BP = 6000
SUPPORT_POOL_BP = 2500
HOUSE_NOMINAL_BP = 1500
COMMISSION_TIER_BP = {"JUNIOR": 3000, "SENIOR": 3800, "MASTER": 4500}
RETAIL_COMMISSION_BP = 1200

# ---------------------------------------------------------------------------
# Cancellation / no-show (PRD §3.8)
# ---------------------------------------------------------------------------
FREE_CANCEL_HOURS = 24
LATE_CANCEL_BAND_HOURS = 4
LATE_CANCEL_BP = 5000
SHORT_NOTICE_BP = 10000
NO_SHOW_BP = 10000
HIGH_DEMAND_UPLIFT_BP = 2000
CHARGE_CAP_BP = 10000
NO_SHOW_GRACE_MINUTES = 15
LATE_CANCEL_RESTRICTION_THRESHOLD = 2
NO_SHOW_RESTRICTION_THRESHOLD = 1

# ---------------------------------------------------------------------------
# Booking / intake / CE / sweep / reports
# ---------------------------------------------------------------------------
BOOKING_LEAD_TIME_MINUTES = 120           # PRD §3.5
MAX_AMENDMENT_ROUNDS = 2                   # PRD §3.4
CE_PER_CATEGORY_CAP_HOURS = 8.0            # PRD §3.3
CE_ETHICS_MINIMUM_HOURS = 2.0              # PRD §3.3
CE_DEFAULT_HOURS_REQUIRED = 12             # PRD §3.3
CE_ROLLING_WINDOW_MONTHS = 24              # PRD §3.3
CE_MAX_HOURS_PER_RECORD = 8                # PRD §3.3
SWEEP_AUTO_CANCEL_HORIZON_HOURS = 48       # PRD §3.10
MAX_REPORT_WINDOW_DAYS = 92                # PRD §3.10

# ---------------------------------------------------------------------------
# Canonical scenario literals
#
# HYDRO90 (90 min, HYDRO, HYDROTHERAPY/ADVANCED, base 30000c, high_demand true,
# consent 2026.1, retail line MARINE) in HYDRO-1 (turnover 30, 4000c/h) with a
# SENIOR therapist (5200c/h, HI) for a PLATINUM guest, starting
# 2026-08-10T17:00:00.000Z.
#
#   room-adjusted   = round_half_up(30000 * 13000 / 10000)          = 39000
#   surcharge rate  = min(1500 + 1000, 2000)                        =  2000
#   surcharge       = round_half_up(39000 * 2000 / 10000)           =  7800
#   subtotal        = 39000 + 7800                                  = 46800
#   raw discount    = round_half_up(46800 * 1500 / 10000) = 7020 -> capped 4000
#   floor           = round_half_up(30000 * 8000 / 10000)           = 24000
#   quoted          = max(46800 - 4000, 24000)                      = 42800
# ---------------------------------------------------------------------------
CANON_TREATMENT_CODE = "HYDRO90"
CANON_ROOM_CODE = "HYDRO-1"
CANON_SKILL_CODE = "HYDROTHERAPY"
CANON_CONSENT_VERSION = "2026.1"
CANON_RETAIL_LINE = "MARINE"
CANON_BASE_PRICE_CENTS = 30000
CANON_DURATION_MINUTES = 90
CANON_TURNOVER_MINUTES = 30
CANON_ROOM_HOURLY_COST_CENTS = 4000
CANON_THERAPIST_HOURLY_COST_CENTS = 5200
CANON_PRACTICE_STATE = "HI"
CANON_LICENSE_NUMBER = "HI-LMT-4410"
CANON_START_AT = "2026-08-10T17:00:00.000Z"
CANON_END_AT = "2026-08-10T18:30:00.000Z"
CANON_BOOKING_CLOCK = "2026-08-03T09:00:00.000Z"
CANON_QUOTED_PRICE_CENTS = 42800
CANON_ROOM_ADJUSTED_CENTS = 39000
CANON_SURCHARGE_CENTS = 7800
CANON_SUBTOTAL_CENTS = 46800
CANON_PRICE_FLOOR_CENTS = 24000
CANON_COMMITTED_ROOM_MINUTES = 120        # 90 + 30 turnover
CANON_COMMITTED_THERAPIST_MINUTES = 90    # turnover excluded
CANON_RETAIL_AMOUNT_CENTS = 4595

# PROVISIONAL settlement row for the canonical appointment (PRD §3.9).
CANON_PROVISIONAL_ROW = {
    "basis_duration_minutes": 90,
    "realized_price_cents": 42800,
    "retail_revenue_cents": 0,
    "service_charge_bp": 1800,
    "service_charge_pool_cents": 7704,
    "gratuity_cents": 0,
    "distributable_pool_cents": 7704,
    "therapist_share_cents": 4622,
    "support_pool_cents": 1926,
    "house_share_cents": 1156,
    "therapist_commission_cents": 16264,
    "retail_commission_cents": 0,
    "labor_cost_cents": 28686,
    "room_fixed_cost_cents": 6000,
    "folio_total_cents": 50504,
    "net_margin_cents": 8114,
}

# FINAL settlement row for the same appointment after 105 delivered minutes,
# a 5000c gratuity and two PURCHASED 4595c attachments (PRD §3.9).
CANON_FINAL_ROW = {
    "basis_duration_minutes": 105,
    "realized_price_cents": 45300,
    "retail_revenue_cents": 9190,
    "service_charge_bp": 1500,
    "service_charge_pool_cents": 6795,
    "gratuity_cents": 5000,
    "distributable_pool_cents": 11795,
    "therapist_share_cents": 7077,
    "support_pool_cents": 2949,
    "house_share_cents": 1769,
    "therapist_commission_cents": 17214,
    "retail_commission_cents": 1102,
    "labor_cost_cents": 34493,
    "room_fixed_cost_cents": 7000,
    "folio_total_cents": 66285,
    "net_margin_cents": 12997,
}

CANON_ACTUAL_DURATION_MINUTES = 105
CANON_GRATUITY_CENTS = 5000
CANON_SETTLEMENT_ADJUSTMENT_CENTS = 6591   # 66285 - (50504 + 4595 + 4595)
CANON_FINAL_FOLIO_BALANCE_CENTS = 66285
