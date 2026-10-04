"""Domain constants for the celebrity video marketplace.

Every number here is restated from the PRD prose: commission rates and tier
thresholds, pricing floors, time windows, the licensing fee table, and the
payout minimum.  Tests import these instead of re-typing literals so that a
single wrong constant is a single wrong file.
"""

# ─── Paths ────────────────────────────────────────────────────────────────

API_PREFIX = "/marketplace"
CLOCK_PATH = "/_clock/set_current_utc"

# ─── Logical clock ────────────────────────────────────────────────────────

# PRD: before any operator sets it, the logical clock reads exactly
# 2026-09-01T00:00:00Z.
CLOCK_INITIAL_INSTANT = "2026-09-01T00:00:00Z"

# ─── Identity / verification windows ──────────────────────────────────────

IDENTITY_AUTO_REJECT_HOURS = 72
ACCEPTANCE_WINDOW_HOURS = 48
AUTO_CONFIRM_HOURS = 72
SUGGESTION_STALE_HOURS = 24

# ─── Rates ────────────────────────────────────────────────────────────────

PERSONAL_RATE_MIN_CENTS = 100
PERSONAL_RATE_MAX_CENTS = 10000000
BUSINESS_RATE_FLOOR_CENTS = 400          # 4x the personal-rate floor
ADVERTISING_RATE_FLOOR_CENTS = 800       # 8x the personal-rate floor
TURNAROUND_MIN_HOURS = 1
TURNAROUND_MAX_HOURS = 336

# ─── Commission tiers ────────────────────────────────────────────────────

COMMISSION_RATE_STANDARD = 0.25
COMMISSION_RATE_SILVER = 0.20
COMMISSION_RATE_GOLD = 0.15
SILVER_THRESHOLD_CENTS = 500000
GOLD_THRESHOLD_CENTS = 2000000
TIER_WINDOW_DAYS = 365

# ─── Payouts ──────────────────────────────────────────────────────────────

MIN_PAYOUT_CENTS = 2500
PARTIAL_REFUND_FRACTION = 0.5

# ─── Licensing fee table ─────────────────────────────────────────────────

LICENSE_FEE_BASE = {"BUSINESS": 50000, "ADVERTISING": 150000}
CHANNEL_FACTOR = {"SOCIAL": 1.0, "WEB": 1.2, "TV": 2.0, "OOH": 1.5}
TERRITORY_MULTIPLIER = {"DOMESTIC": 1.0, "GLOBAL": 1.5}
LICENSE_TIER_DAY_BOUNDARY = 90
LICENSE_TIER_DISCOUNT = 0.9

# ─── Screening ────────────────────────────────────────────────────────────

POLICY_VIOLATION_MARKER = "FLAGGED_POLICY_VIOLATION"
POLICY_VIOLATION_FLAG = "POLICY_VIOLATION"

# ─── Content limits ───────────────────────────────────────────────────────

SCRIPT_INSTRUCTIONS_MAX_CHARS = 2000
RERECORD_NOTES_MAX_CHARS = 1000
DISPUTE_REASON_MAX_CHARS = 1000
MAX_RERECORD_PER_ORDER = 2
VIDEO_DURATION_MIN_SECONDS = 5
VIDEO_DURATION_MAX_SECONDS = 600
STAGE_NAME_MAX_CHARS = 80

# ─── Pause rate limit ────────────────────────────────────────────────────

PAUSE_LIMIT_PER_30_DAYS = 3             # the 4th pause within 30 days fails

# ─── Demand-based pricing suggestion ─────────────────────────────────────

DEMAND_SATURATION = 20
UTILIZATION_SATURATION = 5
W_DEMAND = 0.6
W_UTILIZATION = 0.4
SUGGESTION_SCALE_FACTOR = 0.5
SUGGESTION_ROUNDING_STEP_CENTS = 500
SUGGESTION_ACCEPT_LOWER_MULT = 0.5
SUGGESTION_ACCEPT_UPPER_MULT = 2.0
SUGGESTION_DEMAND_WINDOW_DAYS = 30

# ─── Pagination defaults ─────────────────────────────────────────────────

DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# ─── Reusable expected values for canonical scenarios ────────────────────

# A PERSONAL order on the standard 10000-cent rate confirmed by a STANDARD
# talent: commission 25% of 10000, net is the remainder.
CANONICAL_GROSS_CENTS = 10000
CANONICAL_COMMISSION_CENTS = 2500
CANONICAL_NET_CENTS = 7500

# Canonical licensing scenario: ADVERTISING GLOBAL [TV, WEB], 100 days.
CANONICAL_LICENSE_FEE_CENTS = 71280000
