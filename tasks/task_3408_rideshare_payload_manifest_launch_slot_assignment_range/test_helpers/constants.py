"""Domain thresholds and schedule constants — values taken from PRD prose.

PRD §2.4  logical clock startup default.
PRD §2.3  pagination defaults.
PRD §3.2  tiered price-quote breakpoints and per-kg rates (integer cents).
PRD §3.3  per-line integration fee rate and interface factors.
PRD §3.4  license composite weights and grant threshold.
PRD §3.5  range turnaround buffer minutes.
PRD §3.6  separation base gap and same-interface extra gap seconds.
PRD §3.7  rebooking fee brackets and day-count cutoffs.
"""

# PRD §2.4 — logical clock startup default.
CLOCK_START_UTC = "2026-09-01T00:00:00Z"

# PRD §2.3 — pagination defaults.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# PRD §3.2 — contract price quote tiers (MARGINAL waterfall / FLAT single rate).
TIER1_MAX_KG = 50
TIER1_RATE_CENTS_PER_KG = 600000
TIER2_MAX_KG = 200
TIER2_RATE_CENTS_PER_KG = 500000
TIER3_RATE_CENTS_PER_KG = 425000

# PRD §3.3 — integration fee ledger constants.
INTEGRATION_RATE_CENTS_PER_KG = 12000
INTERFACE_FACTOR_RING_15 = 1.0
INTERFACE_FACTOR_RING_24 = 1.25
INTERFACE_FACTOR_CUBESAT = 0.8
INTERFACE_FACTORS = {
    "RING_15": INTERFACE_FACTOR_RING_15,
    "RING_24": INTERFACE_FACTOR_RING_24,
    "CUBESAT": INTERFACE_FACTOR_CUBESAT,
}

# PRD §3.4 — license composite score weights and grant threshold.
W_DEBRIS = 0.5
W_SPECTRUM = 0.3
W_HISTORY = 0.2
GRANT_THRESHOLD = 70

# PRD §3.5 — range turnaround buffer.
TURNAROUND_MINUTES = 45

# PRD §3.6 — separation sequencing gaps.
BASE_GAP_S = 30
SAME_INTERFACE_EXTRA_GAP_S = 15

# PRD §3.7 — rebooking fee brackets (fraction of quoted_price_cents).
FEE_PCT_FAR = 0.10
FEE_PCT_MID = 0.25
FEE_PCT_NEAR = 0.50
FAR_MIN_DAYS = 61
MID_MIN_DAYS = 31
SECONDS_PER_DAY = 86400

# Canonical windows used across fixtures (all reachable from CLOCK_START_UTC,
# which tests explicitly re-assert via POST /_clock/set_current_utc).
MISSION_WINDOW_OPEN = "2026-10-10T00:00:00Z"
MISSION_WINDOW_CLOSE = "2026-10-20T00:00:00Z"
CONTRACT_WINDOW_OPEN = "2026-10-01T00:00:00Z"
CONTRACT_WINDOW_CLOSE = "2026-10-31T00:00:00Z"
LAUNCH_INSTANT_UTC = "2026-10-15T12:00:00Z"
LICENSE_VALID_UNTIL = "2027-01-01T00:00:00Z"
MISSION_LICENSE_VALID_UNTIL = "2026-12-31T00:00:00Z"
