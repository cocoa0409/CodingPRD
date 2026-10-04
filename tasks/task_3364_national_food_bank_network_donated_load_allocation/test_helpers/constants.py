"""Domain thresholds and canonical literals stated in the PRD.

Every value below is stated verbatim in the PRD; nothing here is invented.
"""

# ── Logical clock (§2.12) ────────────────────────────────────────────
CLOCK_START = "2026-09-01T00:00:00Z"
CLOCK_START_DATE = "2026-09-01"

# ── Share grant allocation (§3.2) ────────────────────────────────────
EPOCH_POOL_SHARES = 100_000
BASE_SHARES_PER_1000 = 120
ACTIVITY_SHARES_PER_10K_LBS = 15
PROBATION_WEIGHT_PCT = 50

# ── Share balance consequences (§2.5, §3.1.2) ────────────────────────
PROBATION_FLOOR_SHARES = 50
REINSTATEMENT_MIN_SHARES = 100

# ── Freight subsidy (§3.6) ───────────────────────────────────────────
FREIGHT_CENTS_PER_MILE = 185
TRANSPORT_SHARE_PCT = {"NATIONAL": 30, "REGIONAL": 55, "LOCAL": 75, "NONE": 100}
REMOTE_DISTANCE_THRESHOLD_MILES = 400
REMOTE_UPLIFT_PCT = 15
MAX_SUBSIDY_PER_LOAD_CENTS = 250_000
MIN_SUBSIDY_CENTS = 5_000

# ── Audit scoring (§3.1, §3.1.1) ─────────────────────────────────────
AUDIT_PASS_THRESHOLD = 85
AUDIT_WEIGHTS = {
    "STORAGE": (60, 20, 20),
    "DISTRIBUTION": (20, 60, 20),
    "REPORTING": (20, 20, 60),
    "COMPREHENSIVE": (40, 30, 30),
}

# ── Recall hold selection (§3.8) ─────────────────────────────────────
MIN_HOLD_LBS = 500

# ── Meal equivalency (§3.7, §3.9) ────────────────────────────────────
NETWORK_MEAL_FACTOR = 1.2
ACTIVITY_BONUS_SHARES_PER_10K_LBS = 15

# ── Temporal windows (§2.12, §3.7, §3.9) ─────────────────────────────
PICKUP_SPACING_HOURS = 24
PICKUP_COMPLETION_TOLERANCE_HOURS = 48

# ── Pagination (§2.3) ────────────────────────────────────────────────
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# ── Common test values ───────────────────────────────────────────────
EPOCH_2026_09 = "2026-09"
DEFAULT_POOL_CENTS = 500_000
