"""Domain thresholds and constants from the PRD calculations (§3.5, §3.9, §3.10)."""

HOLD_TTL_SECONDS = 900  # reservation hold TTL (PRD §3.5)
PROMO_CODE_TTL_HOURS = 72  # promo code expiry (PRD §3.6)
GRACE_PERIOD_HOURS = 72  # viewer grace lapse (PRD §3.4)
POD_SECONDS = 120  # fixed pod length (PRD §3.8)
ALLOWED_SLOT_DURATIONS = (15, 30, 60)
EXCLUSIVE_WEIGHT = 3  # event-weighted amortization (PRD §3.9)
SIMULCAST_WEIGHT = 1
BASELINE_CHURN_PCT = 12  # provisional churn baseline (PRD §3.10)
MARQUEE_UPLIFT_PCT = 5
OVERSUBSCRIBE_MAX_PCT = 50  # PRD §3.5
DEFAULT_LIMIT = 10  # pagination default (PRD §2.3)
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"  # logical clock startup default (PRD §2.8)

TEST_DEFAULTS = {
    "TERM_START": "2026-09-01T00:00:00Z",
    "TERM_END": "2027-09-01T00:00:00Z",
    "REGION": "510",
    "RIGHTS_FEE_CENTS": 1000,
}
