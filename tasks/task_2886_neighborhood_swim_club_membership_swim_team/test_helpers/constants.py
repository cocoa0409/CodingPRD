"""Domain constants for the Neighborhood Swim Club API.

Every figure below is quoted from PRD.md. Nothing here is invented.
"""

# ─── Mount point (PRD §4) ─────────────────────────────
API_PREFIX = "/swim-club"

# ─── Logical clock (PRD §2.5) ─────────────────────────
CLOCK_STARTUP_ISO = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Season defaults (PRD §3.1) ───────────────────────
DEFAULT_BASELINE_BATHER_LOAD = 10
DEFAULT_BATHER_LOAD_CAPACITY = 120
MIN_SEASON_YEAR = 2026
MAX_SEASON_YEAR = 2099

# ─── Guest gate (PRD §3.5) ────────────────────────────
GUEST_FEE_WEEKEND_CENTS = 800
GUEST_FEE_WEEKDAY_CENTS = 500
MIN_GUEST_COUNT = 1
MAX_GUEST_COUNT = 6
RESTRICTED_MAX_GUEST_COUNT = 2

# ─── Swim team (PRD §3.6) ─────────────────────────────
SWIM_TEAM_BASE_FEE_CENTS = 14500
SWIM_TEAM_DISCOUNT_STEP = 0.0625          # 6.25% per swimmer past the first
SWIM_TEAM_DISCOUNT_CAP = 0.25             # capped at 25%
SQUAD_CAPACITY = {"MINI": 20, "JUNIOR": 30, "SENIOR": 30}

VOLUNTEER_CREDIT_VALUES = {
    "TIMER": 1,
    "STARTER": 2,
    "CONCESSIONS": 1,
    "MARSHAL": 1,
    "SCORER": 2,
}
UNDERSTAFFED_PENALTY_PER_CREDIT_CENTS = 7500
VOLUNTEER_BUYOUT_PER_CREDIT_CENTS = 3500
VOLUNTEER_CREDIT_CAP = 10

# ─── Parties (PRD §3.7) ───────────────────────────────
BATHERS_PER_GUARD = 25
MIN_GUARD_COUNT = 1
GUARD_HOUR_RATE_CENTS = 2200
ZONE_BASE_FEE_CENTS = {
    "PAVILION": 6000,
    "SHALLOW_END": 9000,
    "WHOLE_FACILITY": 20000,
}
INCLUDED_GUESTS = 10
GUEST_OVERAGE_FEE_CENTS = 700
DISCOUNT_TIER_15_THRESHOLD_CENTS = 45000
DISCOUNT_TIER_10_THRESHOLD_CENTS = 25000
DISCOUNT_RATE_15 = 0.15
DISCOUNT_RATE_10 = 0.10
FULL_REFUND_LEAD_DAYS = 7

# ─── Guard shifts (PRD §3.8) ──────────────────────────
SHIFT_REST_BUFFER_MINUTES = 30

# ─── Invoicing (PRD §3.4) ─────────────────────────────
LATE_PENALTY_RATE = 0.035
INSTALLMENT_BOND_DIVISOR = 4
DELINQUENCY_TOLERANCE_CENTS = 0

# ─── Waitlist queue (PRD §3.2) ────────────────────────
PRIORITY_TIER_RANK = {"LEGACY": 0, "SIBLING": 1, "STANDARD": 2}
OFFER_WINDOW_DAYS = 14
MAX_DEFERRALS = 2

# ─── Conduct (PRD §3.9) ───────────────────────────────
CONDUCT_POINT_VALUES = {"MINOR": 2, "MAJOR": 4, "SEVERE": 8}
SUSPENSION_POINT_THRESHOLD = 6
EXPULSION_POINT_THRESHOLD = 10
CONDUCT_LOOKBACK_DAYS = 730
APPEAL_WINDOW_DAYS = 10
MAX_APPEALS = 2
SANCTION_TO_STANDING = {
    "WARNING": "GOOD_STANDING",
    "PROBATION": "PROBATION",
    "SUSPENSION": "SUSPENDED",
    "EXPULSION": "EXPELLED",
}
STANDING_SEVERITY_RANK = {
    "GOOD_STANDING": 0,
    "PROBATION": 1,
    "SUSPENDED": 2,
    "EXPELLED": 3,
}

# ─── Capital reserve (PRD §3.4 / §3.10) ───────────────
PER_MEMBERSHIP_RESERVE_CONTRIBUTION_CENTS = 5000

# ─── A UUID that is well-formed but never minted by the server ───
MISSING_UUID = "11111111-1111-4111-8111-111111111111"
