"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical-clock defaults (PRD §2.8: startup value is exactly 2026-09-01T00:00:00Z).
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"
# In-window operating instant: minute-of-day 540 falls inside [480, 720).
CLOCK_IN_WINDOW = "2026-09-01T09:00:00Z"
CLOCK_AT_WINDOW_START = "2026-09-01T08:00:00Z"  # minute 480 (inclusive start)
CLOCK_AT_WINDOW_END = "2026-09-01T12:00:00Z"  # minute 720 (exclusive end)

# Standard service dates. 2026-09-01 is a TUE; 2026-09-02 is a WED.
SERVICE_DATE_TUE = "2026-09-01"
SERVICE_DATE_WED = "2026-09-02"

# Delivery window used by the standard store fixture.
WINDOW_START_MINUTE = 480
WINDOW_END_MINUTE = 720

# Freshness / stale-window constants (PRD §3.5, §3.7): days_to_expiry > 5 is
# deliverable; days_to_expiry <= 5 is stale-eligible.
FRESHNESS_MIN_DAYS = 5
STALE_WINDOW_DAYS = 5
# On service date 2026-09-01: 2026-09-06 => 5 days (stale-eligible, undeliverable);
# 2026-09-07 => 6 days (deliverable, not stale-eligible); 2026-09-20 => 19 days.
EXPIRY_STALE_ON_TUE = "2026-09-06"
EXPIRY_FRESH_SIX_ON_TUE = "2026-09-07"
EXPIRY_FRESH = "2026-09-20"
EXPIRY_FRESH_LATE = "2026-09-30"

# Money constants (PRD §3.7, §3.9, §3.10).
SALVAGE_RATE_NUM = 2  # 0.40 as 2/5 for integer-exact expectations
SALVAGE_RATE_DEN = 5
VARIANCE_TOLERANCE_CENTS = 200
GOLD_MAX_OOS = 0.02
SILVER_MAX_OOS = 0.05
STALE_WATCH_THRESHOLD = 0.08

TEST_DEFAULTS = {
    "CASE_PRICE_CENTS": 500,
    "STORE_CREDIT_CAP_CENTS": 100000,
    "BASE_CAPACITY_CASES": 100,
    "TRUCK_CAP_CASES": 200,
}
