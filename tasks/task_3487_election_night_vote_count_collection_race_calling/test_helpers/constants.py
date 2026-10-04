"""Domain thresholds and clock constants — every value is stated in the PRD.

Sources:
- Logical clock startup default: PRD §2.4 ("reads exactly 2026-09-01T00:00:00Z").
- QC thresholds: PRD §3.4 (deviation strictly greater than 0.40 flags;
  swing strictly greater than 0.25 flags).
- Recount margin threshold: PRD §3.7 (margin_pct no greater than 0.005,
  inclusive).
- Reliability scoring: PRD §3.3 (start 100; -25 per no-show; -10 per voided
  report; +2 per accepted report; clamp 0..100; recent window 365 days).
- Delivery pricing: PRD §3.8 (999-cent vote update, 4999-cent call;
  multipliers 1.0 PREMIUM / 0.6 STANDARD / 0.35 BASIC).
- Pagination: PRD §2.3 (limit default 10, min 1, max 100).
"""

# --- Logical clock (PRD §2.4) ---------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# Clock position used while building an event's SETUP-phase records.
SETUP_CLOCK = "2026-10-15T00:00:00Z"

# Canonical 2026 election day; reports, check-ins, and calls rehearse here.
ELECTION_DAY = "2026-11-03"
ELECTION_DAY_CLOCK = "2026-11-03T13:00:00Z"
ELECTION_DAY_EARLY_CLOCK = "2026-11-03T07:00:00Z"   # before the default window
ELECTION_DAY_LATE_CLOCK = "2026-11-03T21:00:00Z"    # after the default window

# Historical rehearsal event (a past election day is legal per PRD §3.1).
# Any fixture using these MUST move the logical clock backward explicitly.
HISTORICAL_EVENT_DATE = "2024-11-05"
HISTORICAL_WINDOW_START = "2024-11-05T08:00:00Z"
HISTORICAL_WINDOW_END = "2024-11-05T20:00:00Z"
HISTORICAL_NO_SHOW_CLOCK = "2024-11-06T00:00:00Z"   # past the historical window

# Default stringer deployment window on election day (half-open).
DEFAULT_WINDOW_START = "2026-11-03T08:00:00Z"
DEFAULT_WINDOW_END = "2026-11-03T20:00:00Z"

# --- Quality-control thresholds (PRD §3.4; both strict) --------------------
QC_VOTE_DEVIATION_PCT = 0.40
QC_SWING_PCT = 0.25

# --- Recount filing threshold (PRD §3.7; inclusive) -------------------------
RECOUNT_MARGIN_THRESHOLD = 0.005

# --- Stringer reliability scoring (PRD §3.3) --------------------------------
RELIABILITY_INITIAL = 100
NO_SHOW_PENALTY = 25
VOIDED_PENALTY = 10
ACCEPTED_CREDIT = 2
RELIABILITY_SCORE_FLOOR = 0
RELIABILITY_SCORE_CAP = 100
RECENT_FORM_WINDOW_DAYS = 365

# --- Delivery pricing (PRD §3.8) --------------------------------------------
VOTE_UPDATE_BASE_FEE_CENTS = 999
CALL_BASE_FEE_CENTS = 4999
TIER_MULTIPLIER_PREMIUM = 1.0
TIER_MULTIPLIER_STANDARD = 0.6
TIER_MULTIPLIER_BASIC = 0.35
TIER_MULTIPLIERS = {
    "PREMIUM": TIER_MULTIPLIER_PREMIUM,
    "STANDARD": TIER_MULTIPLIER_STANDARD,
    "BASIC": TIER_MULTIPLIER_BASIC,
}
BASE_FEE_CENTS = {
    "VOTE_UPDATE": VOTE_UPDATE_BASE_FEE_CENTS,
    "CALL": CALL_BASE_FEE_CENTS,
}

# --- Pagination (PRD §2.3) ---------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Retraction reason recorded when the recount cascade drives the retraction
# (PRD §3.6/§3.7).
RECOUNT_OVERTURNED_REASON = "RECOUNT_OVERTURNED"
