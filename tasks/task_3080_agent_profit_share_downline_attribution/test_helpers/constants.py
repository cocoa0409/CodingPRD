"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # The annual company-dollar cap per cap year (PRD §3.5).
    "ANNUAL_CAP": 20000.00,
    # The company-dollar split rate (PRD §3.5).
    "COMPANY_DOLLAR_RATE": 0.30,
    # The profit-share pool rate (PRD §3.6 / §3.9).
    "PROFIT_SHARE_POOL_RATE": 0.52,
    # Vesting: inclusive day threshold and provisional month divisor (PRD §3.10).
    "VESTING_DAYS": 1095,
    "VESTING_MONTHS": 36,
    # Sponsorship closure depth cap (PRD §3.3).
    "MAX_DEPTH": 7,
    # Dispute filing window in days, inclusive deadline (PRD §3.4).
    "DISPUTE_WINDOW_DAYS": 90,
    # Distribution level rates by depth (PRD §3.8).
    "LEVEL_RATES": {1: 0.50, 2: 0.10, 3: 0.05, 4: 0.05, 5: 0.075, 6: 0.10, 7: 0.125},
}

TEST_DEFAULTS = {
    "JOIN_DATE": "2026-09-01T00:00:00Z",
    "CLOCK_DEFAULT": "2026-09-01T00:00:00Z",
    "PERIOD_MONTH": "2026-09",
    "DISPUTE_DEADLINE_JOIN_2026_09_01": "2026-11-30T00:00:00Z",
}
