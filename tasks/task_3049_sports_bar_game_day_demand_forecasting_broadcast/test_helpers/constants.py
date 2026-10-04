"""Domain constants: API mount prefix, pricing/threshold values, and defaults.

Every numeric literal here names a value the PRD states verbatim (rates,
thresholds, weights, hold minutes), so tests can assert against a named
constant rather than a magic number.
"""

# The API is mounted under /api (PRD §1: "The API is mounted under `/api`").
API_PREFIX = "/api"

# ─── Venue / volatility ──────────────────────────────────────────────────────
WING_COST_REFERENCE_CENTS_PER_LB = 180
VOLATILITY_RISK_THRESHOLD = 0.25

# ─── Wing prep forecast (PRD §3.1) ──────────────────────────────────────────
DINE_IN_SHARE = 0.70
WING_EATER_SHARE = 0.40
PIECES_PER_PERSON = 15
FORECAST_WINDOW_START_HOUR_UTC = 14
FORECAST_WINDOW_HOURS = 48

# ─── Group-day weights (PRD §3.1) ───────────────────────────────────────────
GROUP_DAY_WEIGHTS = {
    "FF_NFL": 0.5,
    "FF_NBA": 0.4,
    "MLB": 0.3,
    "NHL": 0.3,
    "NCAA": 0.2,
    "MMA": 0.3,
    "BOXING": 0.3,
    "ENTERTAINMENT": 0.1,
}
GROUP_DAY_THRESHOLD = 2.0

# ─── Wing pricing (PRD §3.5) ─────────────────────────────────────────────────
BASE_UNIT_PRICE_CENTS = 150
QUANTITY_TIER_THRESHOLD_PIECES = 50
QUANTITY_TIER_MULTIPLIER = 0.95
SURCHARGE_LOOKBACK_DAYS = 30
SURCHARGE_THRESHOLD_PIECES = 5000
SURCHARGE_MULTIPLIER = 1.10
PROMO_PORTION_SIZE = 10

# ─── Check arithmetic (PRD §2.7, §3.5) ───────────────────────────────────────
TAX_RATE = 0.05
WINGS_PER_PORTION = 10

# ─── Waitlist / table hold (PRD §3.4) ────────────────────────────────────────
BASE_WAIT_MINUTES_PER_GROUP = 15
GROUP_SEAT_CAP = 8
HOLD_MINUTES = 15
KICKOFF_OVERRIDE_HOLD_MINUTES = 25
NO_SHOW_LIMIT = 3

# ─── Blackout window (PRD §3.2) ──────────────────────────────────────────────
BLACKOUT_PRE_GAME_MINUTES = 30
BLACKOUT_POST_GAME_MINUTES = 60
NCAA_DEFAULT_BLACKOUT_RADIUS_MILES = 75

# ─── Staffing (PRD §3.7) ─────────────────────────────────────────────────────
STAFFING_COVER_SHARE = 0.4
FOH_PER_COVERS = 60
BOH_PER_COVERS = 100

# ─── Trivia scoring (PRD §3.8) ───────────────────────────────────────────────
TRIVIA_BASE_POINTS = 100
TRIVIA_SPEED_MAX = 50
TRIVIA_SPEED_DECAY_PER_SECOND = 2.5
TRIVIA_STREAK_INTERVAL = 3
TRIVIA_STREAK_BONUS = 25

# ─── Logical clock default start (PRD §2.4) ──────────────────────────────────
CLOCK_DEFAULT_START_UTC = "2026-09-01T00:00:00Z"

# ─── Sensible venue defaults used across factories and fixtures ──────────────
DEFAULT_VENUE = {
    "name": "Downtown",
    "market_zip": "14201",
    "capacity_seats": 200,
    "wing_cost_cents_per_lb": WING_COST_REFERENCE_CENTS_PER_LB,
}
