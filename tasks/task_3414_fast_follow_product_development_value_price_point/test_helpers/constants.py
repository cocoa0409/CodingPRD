"""Domain constants — every value sourced from PRD prose.

Sections: logical clock, momentum score, price points / cost targets,
packaging lead time, formula development, certification, launch quantity,
markdown depth, occupancy buffer, sampling cap, pagination.
"""

__all__ = [
    "LOGICAL_CLOCK_START",
    "VELOCITY_CAP_PER_DAY",
    "GROWTH_CAP",
    "W_VELOCITY",
    "W_GROWTH",
    "W_SIGNAL",
    "TREND_SELECT_THRESHOLD",
    "PRICE_POINTS",
    "TARGET_UNIT_COST_BY_PRICE_POINT",
    "TOOLING_NEW_WEEKS",
    "TOOLING_REUSE_WEEKS",
    "COMPRESSED_FORMULA_WEEKS",
    "MAX_FORMULA_ROUNDS",
    "CERT_VALIDITY_DAYS",
    "FACINGS_WEEKLY_SELLTROUGH",
    "LAUNCH_WEEKS",
    "TREND_DECAY_PCT_PER_WEEK",
    "MARKDOWN_RISK_CAP",
    "MARKDOWN_TIER1_MAX_WEEKS",
    "MARKDOWN_TIER2_MAX_WEEKS",
    "MARKDOWN_TIER3_MAX_WEEKS",
    "MARKDOWN_DEPTH_TIER1",
    "MARKDOWN_DEPTH_TIER2",
    "MARKDOWN_DEPTH_TIER3",
    "MARKDOWN_DEPTH_TIER4",
    "RESET_GAP_DAYS",
    "SAMPLE_CAP_PCT",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "DEFAULT_WINDOW_START",
    "DEFAULT_WINDOW_END",
    "DEFAULT_REVIEW_DATE",
    "DEFAULT_OCCUPANCY_START",
    "DEFAULT_OCCUPANCY_END",
    "DEFAULT_QUOTE_VALID_UNTIL",
    "DEFAULT_PRODUCTION_QUARTER",
    "DEFAULT_SEASON",
    "CLOCK_INSIDE_WINDOW",
    "CLOCK_AFTER_WINDOW",
    "CLOCK_AT_REVIEW_DATE",
    "CLOCK_OCCUPANCY_START",
    "CERT_EXPIRY_FROM_START",
    "CLOCK_PAST_CERT_EXPIRY",
    "CLOCK_MARKDOWN_WEEK4",
    "CLOCK_MARKDOWN_WEEK9",
]

# --- Logical clock (PRD 2.4) ------------------------------------------------
#: The clock reads exactly this before any call sets it.
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

# --- Momentum score (PRD 3.1) ------------------------------------------------
#: velocity component: mention_velocity_7d / 5000, capped at 1
VELOCITY_CAP_PER_DAY = 5000
#: growth component: engagement_growth_pct / 2, capped at 1
GROWTH_CAP = 2.0
#: component weights: one half / three tenths / one fifth
W_VELOCITY = 0.5
W_GROWTH = 0.3
W_SIGNAL = 0.2
#: selection gate: momentum_score must be at least seventy (inclusive)
TREND_SELECT_THRESHOLD = 70.0

# --- Fixed price points and derived cost targets (PRD 3.2) -------------------
#: target_price_point_cents membership set
PRICE_POINTS = (300, 600, 1000, 1500, 2000)
#: worked tier results: floor(price * ratio) with ratios 0.28/0.26/0.24/0.22
TARGET_UNIT_COST_BY_PRICE_POINT = {300: 84, 600: 168, 1000: 260, 1500: 360, 2000: 440}

# --- Packaging lead time (PRD 3.3) -------------------------------------------
TOOLING_NEW_WEEKS = 14
TOOLING_REUSE_WEEKS = 5

# --- Formula development (PRD 3.4) -------------------------------------------
#: due_at := created_at + 6 weeks (compressed formula timeline)
COMPRESSED_FORMULA_WEEKS = 6
#: rejecting a sample at the third round auto-abandons the project
MAX_FORMULA_ROUNDS = 3

# --- Cruelty-free certification (PRD 3.6) ------------------------------------
#: cert_expires_at := review instant + 365 days
CERT_VALIDITY_DAYS = 365

# --- Launch quantity (PRD 3.8) -----------------------------------------------
#: capacity_units = facings * 12 * 8
FACINGS_WEEKLY_SELLTROUGH = 12
LAUNCH_WEEKS = 8
#: markdown_risk_pct = min(whole weeks since trend * 0.05, 0.40)
TREND_DECAY_PCT_PER_WEEK = 0.05
MARKDOWN_RISK_CAP = 0.40

# --- Markdown depth tiers (PRD 3.8) ------------------------------------------
#: 0% when four weeks or fewer since launch; 30% through 8; 50% through 12;
#: 70% beyond
MARKDOWN_TIER1_MAX_WEEKS = 4
MARKDOWN_TIER2_MAX_WEEKS = 8
MARKDOWN_TIER3_MAX_WEEKS = 12
MARKDOWN_DEPTH_TIER1 = 0.00
MARKDOWN_DEPTH_TIER2 = 0.30
MARKDOWN_DEPTH_TIER3 = 0.50
MARKDOWN_DEPTH_TIER4 = 0.70

# --- Shelf occupancy buffer (PRD 3.7) ----------------------------------------
#: closed occupancy intervals need a 14-day reset gap per position; exactly
#: 14 days is allowed
RESET_GAP_DAYS = 14

# --- Sampling cap (PRD 3.8) ---------------------------------------------------
#: samples cap = floor(qty_locked_units * 0.10)
SAMPLE_CAP_PCT = 0.10

# --- Pagination (PRD 2.3) -----------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Canonical fixture timeline ----------------------------------------------
# Default line-review window / review date / occupancy interval used by the
# composite fixtures. All are at or after LOGICAL_CLOCK_START and advance
# monotonically, so every one is reachable via the logical clock.
DEFAULT_WINDOW_START = "2026-10-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-10-15T00:00:00Z"
DEFAULT_REVIEW_DATE = "2026-10-20T00:00:00Z"
DEFAULT_OCCUPANCY_START = "2026-11-01T00:00:00Z"
DEFAULT_OCCUPANCY_END = "2027-01-31T00:00:00Z"
DEFAULT_QUOTE_VALID_UNTIL = "2026-12-31T00:00:00Z"
DEFAULT_PRODUCTION_QUARTER = "2026-Q4"
DEFAULT_SEASON = "2026-HO"

#: Named clock positions used by multi-step scenarios (all >= start, applied
#: in increasing order along any single fixture chain).
CLOCK_INSIDE_WINDOW = "2026-10-02T00:00:00Z"
CLOCK_AFTER_WINDOW = "2026-10-16T00:00:00Z"
CLOCK_AT_REVIEW_DATE = "2026-10-21T00:00:00Z"
CLOCK_OCCUPANCY_START = DEFAULT_OCCUPANCY_START
#: CERTIFIED at the clock start lapses at start + 365 days.
CERT_EXPIRY_FROM_START = "2027-09-01T00:00:00Z"
CLOCK_PAST_CERT_EXPIRY = "2027-09-02T00:00:00Z"
#: Exactly 4 weeks after a 2026-11-01 launch (markdown depth tier boundary).
CLOCK_MARKDOWN_WEEK4 = "2026-11-29T00:00:00Z"
#: 9 weeks after a 2026-11-01 launch (markdown depth 0.50).
CLOCK_MARKDOWN_WEEK9 = "2027-01-05T00:00:00Z"
