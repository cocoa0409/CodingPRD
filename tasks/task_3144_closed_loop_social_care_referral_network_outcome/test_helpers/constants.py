"""Domain thresholds and default constants from the PRD."""

DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

NETWORK_DEFAULTS = {
    "max_reassignment_count": 3,
    "auto_accept_window_hours": 72,
    "unresolved_aging_days": 30,
    "referral_expiry_days": 60,
    "network_escrow_cents": 0,
}

# k-anonymity suppression threshold for report demographic cells.
K_ANONYMITY_THRESHOLD = 5

TEST_DEFAULTS = {
    "CATEGORY_CODE": "FOOD",
    "CATEGORY_NAME": "Food",
    "ZIP": "94110",
    "DOB": "1990-01-01",
    "RATE_CENTS_PER_UNIT": 100,
    "EFFECTIVE_AT": "2026-09-01T00:00:00Z",
}
