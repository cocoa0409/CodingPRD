"""Domain thresholds taken from the pacing, freshness, quality and auction rules.

These are the literal constants the PRD pins; tests assert against them rather
than re-deriving them from response data.
"""

# ─── Logical clock ────────────────────────────────────
CLOCK_START_UTC = "2026-09-01T00:00:00Z"
DAY_SECONDS = 86400

# ─── Posting freshness ────────────────────────────────
STALE_AFTER_DAYS = 30
EXPIRED_AFTER_DAYS = 60

# ─── Scheduled pacing multiplier ──────────────────────
WARMUP_FRACTION = 0.05
MIN_MULTIPLIER = 0.0
MAX_MULTIPLIER = 2.0
MULTIPLIER_PRECISION = 3

# ─── Auction clearing ─────────────────────────────────
MIN_INCREMENT_CENTS = 1
QUALITY_SCALE = 100
MIN_BID_CENTS = 1

# ─── Employer quality signal ──────────────────────────
TIER_HIGH_MIN_BPS = 6000
TIER_MID_MIN_BPS = 3000
TIER_HIGH = 100
TIER_MID = 70
TIER_LOW = 40
SCORE_FLOOR = 0
SCORE_CEILING = 100
HIRE_WEIGHT = 30
INTERVIEW_WEIGHT = 10
REJECT_WEIGHT = 10

# ─── Relevance score weights ──────────────────────────
KEYWORD_FULL = 40
KEYWORD_PARTIAL = 20
LOCATION_EXACT = 35
LOCATION_PREFIX = 15
FRESHNESS_FRESH = 25
FRESHNESS_STALE = 10
RELEVANCE_MAX = 100
RELEVANCE_MAX_UNMAPPED = 65

# ─── Daily capacity floor for BUDGET_HOLD ─────────────
BUDGET_HOLD_FLOOR_CENTS = 1000

# ─── Refund window ────────────────────────────────────
REFUND_WINDOW_HOURS = 24

# ─── Pagination ───────────────────────────────────────
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ─── Convenience defaults used across fixtures ────────
TEST_DEFAULTS = {
    "DAILY_BUDGET_CENTS": 100000,
    "TOTAL_BUDGET_CENTS": 1000000,
    "CPC_BID_CENTS": 300,
    "CPA_BID_CENTS": 900,
    "SEEKER_LOCATION": "Austin, TX",
    "POSTING_LOCATION": "Austin, TX",
}

HOLD_UNIT_CENTS = 100