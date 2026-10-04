"""Domain thresholds and pinned literals from the PRD (§2.3, §2.4, §2.8, §3.5-§3.9)."""

# Logical clock (PRD §2.4): the clock reads exactly this before any set call.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Standard agreement window used by fixtures: contains the default clock date
# (PRD §3.5 requires start_date strictly before end_date; order delivery dates
# must land inside the window).
AGREEMENT_WINDOW_START = "2026-08-01"
AGREEMENT_WINDOW_END = "2027-08-31"

# Rebate tier table (PRD §3.7) — inclusive lower-bound thresholds.
TIER1_THRESHOLD_CENTS = 100000
TIER1_RATE = 0.01
TIER2_THRESHOLD_CENTS = 500000
TIER2_RATE = 0.02
TIER3_THRESHOLD_CENTS = 1000000
TIER3_RATE = 0.03
TIER4_THRESHOLD_CENTS = 2000000
TIER4_RATE = 0.04
BASE_RATE_FLOOR = 0.005
PL_SHARE_BONUS_THRESHOLD = 0.30
PL_SHARE_BONUS_RATE = 0.005
COMPLIANT_MULTIPLIER = 1.0
NONCOMPLIANT_MULTIPLIER = 0.5

# Rolling fill-rate window (PRD §3.6): trailing ninety days, both ends inclusive.
ROLLING_WINDOW_DAYS = 90
# Final fill rate when every unit was cancelled (zero denominator) — PRD §3.6.
EMPTY_DENOMINATOR_FILL = 100.00

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Fill-rate precision: 2 decimal places, rounded half up (PRD §2.8).
PCT_TOLERANCE = 0.001

# Auto-resolve rationale stamped on still-PENDING substitution requests (PRD §3.8).
AUTO_RESOLVED_RATIONALE = "AUTO_RESOLVED"
