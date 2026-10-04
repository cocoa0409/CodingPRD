"""Domain thresholds and wire constants, taken from the PRD.

Every value here is named by a PRD rule that a test asserts against: the
points window and disqualification thresholds, the commercial conviction
posting deadline, the dues schedule, the timeliness scale, pagination
bounds, and the logical clock's startup instant. Dates derived from these
constants must always be anchored to an explicit logical-clock value (the
startup default below, or an instant the test itself set), never to the
host wall clock.
"""

# ── Logical clock (PRD §2.4) ─────────────────────────────────────────────────

# Startup default, exactly as the PRD pins it. Tests that need another
# instant set it explicitly through the clock endpoint.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-09-01"

# Default certification window used by fixtures: it contains the startup
# instant and every instant any scenario moves the clock to (through 2027).
DEFAULT_CERT_WINDOW_START = "2026-08-01T00:00:00Z"
DEFAULT_CERT_WINDOW_END = "2027-12-31T00:00:00Z"

# ── Points and disqualifications (PRD §3.4) ──────────────────────────────────

POINTS_WINDOW_DAYS = 1095            # trailing window, both boundary days included
POINTS_THRESHOLD = 12                # >= triggers an AUTO_POINTS disqualification
POINTS_BASE_DAYS = 90                # base duration for AUTO_POINTS
MAJOR_BASE_DAYS = 365                # base duration for AUTO_MAJOR
DURATION_MULTIPLIER_CAP = 3          # duration multiplier never exceeds this
CONVICTION_POSTING_DEADLINE_DAYS = 30  # inclusive: exactly 30 days is timely
CONVICTION_POINTS_MIN = 1
CONVICTION_POINTS_MAX = 6

# ── Timeliness score (PRD §3.4) ─────────────────────────────────────────────

TIMELINESS_SCORE_FULL_BP = 10000     # basis points; also the empty-set value

# ── Annual dues schedule (PRD §3.8) ─────────────────────────────────────────

BASE_FEE_CENTS = 2_500_000
ANNUAL_CAP_CENTS = 20_000_000
TIER1_LIMIT = 10_000                 # transactions priced at the first rate
TIER2_LIMIT = 50_000                 # cumulative end of the second bracket
TIER1_RATE_CENTS = 12.5
TIER2_RATE_CENTS = 10.5
TIER3_RATE_CENTS = 8.5
MULTIPLIER_FLOOR = 0.85              # binds from four certified systems onward
DISCOUNT_STEP = 0.05                 # five hundredths per system beyond the first
AUDIT_QUARTERS_COUNT = 4             # actual_volume_quarters length at audit

# ── Pagination (PRD §2.3) ────────────────────────────────────────────────────

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ── Vehicle titles (PRD §3.7) ────────────────────────────────────────────────

VIN_LENGTH = 17
