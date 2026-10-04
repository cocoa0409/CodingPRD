"""Domain thresholds — numeric constants from the PRD's pricing, settlement,
and fraud rules."""

THRESHOLDS = {
    # Goodwill chargeback: supplier absorbs goodwill iff ratio strictly > 0.15.
    "GOODWILL_SUPPLIER_THRESHOLD": 0.15,
    # Fraud scoring thresholds.
    "REPEAT_WIN_THRESHOLD": 3,
    "REPEAT_WIN_PENALTY": 25,
    "WATCH_THRESHOLD": 20,
    "BLOCKED_THRESHOLD": 50,
}

TEST_DEFAULTS = {
    "SUPPLIER_COMMISSION_PCT": 0.15,
    "SUPPLIER_MIN_DISCOUNT_PCT": 0.10,
    "PUBLISHED_RATE_CENTS": 20000,
    "OPAQUE_RATE_CENTS": 15000,
    "ROOMS_ALLOCATED": 5,
    "WINDOW_CHECK_IN": "2026-10-01T00:00:00Z",
    "WINDOW_CHECK_OUT": "2026-10-05T00:00:00Z",
    "STAY_CHECK_IN": "2026-10-02T00:00:00Z",
    "STAY_CHECK_OUT": "2026-10-04T00:00:00Z",
    # FIXED-mode 2-night floor for the default setup:
    # ceil(15000 * 2 * (1 - 0.10)) = 27000.
    "DEFAULT_FIXED_PRICE_CENTS": 27000,
    "CLOCK_START": "2026-09-01T00:00:00Z",
}
