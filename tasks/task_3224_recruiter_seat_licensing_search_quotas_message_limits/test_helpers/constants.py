"""Domain thresholds — numeric constants from PRD calculations."""

# PRD section 2.9: product tier derived limits
TIER_LIMITS = {
    "RECRUITER_LITE": {
        "monthly_credit_per_seat": 30,
        "monthly_search_quota_per_seat": 100,
        "search_result_page_cap": 40,
    },
    "RECRUITER_PRO": {
        "monthly_credit_per_seat": 100,
        "monthly_search_quota_per_seat": 1000,
        "search_result_page_cap": 100,
    },
    "RECRUITER_CORP": {
        "monthly_credit_per_seat": 150,
        "monthly_search_quota_per_seat": 10000,
        "search_result_page_cap": 1000,
    },
}

# PRD section 3.5: spam-strike throttle threshold
THROTTLE_THRESHOLD = 3

# PRD section 3.8: privacy aggregation floor for talent insight reports
AGGREGATION_FLOOR = 25

# PRD section 3.1: a billing period is always 30 days
PERIOD_DAYS = 30

# PRD section 3.9: one dollar per credit as the contract accounting unit
CREDIT_UNIT_CENTS = 100

# PRD section 3.10: default logical clock before any set
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# PRD section 3.6: posting constraints
MIN_BUDGET_CENTS = 1000
MIN_DAILY_CAP_CENTS = 100

# PRD section 3.1 / 2.9: seat_cap bounds
SEAT_CAP_MIN = 1
SEAT_CAP_MAX = 5000

# PRD section 3.5: pinned candidates cap on search projects
PINNED_CANDIDATES_MAX = 100

TEST_DEFAULTS = {
    "SEAT_CAP": 5,
    "SEATS_PURCHASED_INITIAL": 1,
    "POSTING_BUDGET_CENTS": 10000,
    "POSTING_DAILY_CAP_CENTS": 5000,
}
