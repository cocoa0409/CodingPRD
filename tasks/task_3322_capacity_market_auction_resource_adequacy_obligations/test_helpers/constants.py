"""Domain thresholds and test defaults — numeric constants from the PRD."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # re-export

# PRD §3.1 — reliability requirement roll-up
REQUIREMENT_MW_DECIMALS = 3

# PRD §3.2 — accreditation
FULL_SAMPLE_HOURS = 100
ACCREDITATION_FACTOR_CAP = 1.0

# PRD §3.4 — seller offer cap
NET_CONE_PER_MW_DAY = 390.0
ACR_BASE = 60.0
ACR_CREDIT_SLOPE = 0.1
MITIGATION_FLOOR_FRACTION = 0.1
SHORTAGE_PRICE_PER_MW_DAY = 390.0

# PRD §3.6 — performance assessment and non-performance charge
HOURS_PER_DAY = 24.0
BONUS_CAP_RATIO = 1.5
NO_OBLIGATION_RATIO = 1.0
TIER1_RATIO = 0.6
TIER2_RATIO = 0.3
TIER1_MULTIPLIER = 1.0
TIER2_MULTIPLIER = 1.5
TIER3_MULTIPLIER = 2.0
BONUS_MW_CAP_FRACTION = 0.5

# PRD §3.5 — commitment default gate
DEFAULT_SCORE_THRESHOLD = 0.40
DEFAULT_MIN_FINALIZED_ASSESSMENTS = 2

# PRD §3.8 — redistribution
PERFORMER_RATIO_FLOOR = 1.0

# PRD §2.9 — logical clock
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Canonical planning period used across setups (PRD §3.1).
DY_LABEL = "2029/2030"
DY_START = "2029-06-01T00:00:00Z"
DY_END = "2030-05-31T23:59:59Z"

TEST_DEFAULTS = {
    "PEAK_LOAD_MW": 10.0,
    "RESERVE_MARGIN_PCT": 0.25,
    "POOL_WIDE_AVG_EFORD": 0.04,
    "CREDIT_SCORE": 900,
    "NAMEPLATE_MW": 100.0,
    "CLASS_AVG_FACTOR": 0.85,
    "FORCED_OUTAGE_RATE": 0.10,
    "SCARCITY_HOURS_SAMPLED": 100,
}
