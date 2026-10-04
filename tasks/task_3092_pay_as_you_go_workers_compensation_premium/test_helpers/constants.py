"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.5).
CLOCK_START = "2026-09-01T00:00:00Z"

# Day-count thresholds (PRD §2.5, §3.5, §3.8) — all inclusive at the lower boundary.
THRESHOLDS = {
    "GRACE_CYCLE_COUNT": 1,
    "DELINQUENT_CYCLE_COUNT": 2,
    "NONREPORTING_CYCLE_COUNT": 3,
    "BROKEN_TO_NONREPORTING_DAYS": 21,
    "NONREPORTING_TO_CANCEL_DAYS": 35,
    "INVOICE_DUE_DAYS": 7,
    "OVERDUE_TO_SUSPENDED_DAYS": 14,
}

# Premium arithmetic pins (PRD §3.3).
CALC = {
    "RATE_DIVISOR": 10000,          # per-$100 factor and cents conversion combined
    "DAYS_PER_WEEK": 7,             # executive cap week count
}

# Shared rating-table fixture values used across the test suite.
RATING_TABLES = {
    "CA": {
        "state_code": "CA",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
        "monopolistic": False,
        "per_capita_admin_fee_cents": 250,
        "expense_constant_cents": 30000,
        "min_payroll_threshold_cents": 10000,
        "state_minimum_premium_cents": 50000,
        "ot_basis": "NET",
        "class_rates": [
            {"class_code": "8810", "rate_per_100_cents": 125},
            {"class_code": "5645", "rate_per_100_cents": 890},
            {"class_code": "8812", "rate_per_100_cents": 160},
        ],
        "max_payroll_per_executive_cents": 250000,
    },
    "NV": {
        "state_code": "NV",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
        "monopolistic": False,
        "per_capita_admin_fee_cents": 400,
        "expense_constant_cents": 45000,
        "min_payroll_threshold_cents": 0,
        "state_minimum_premium_cents": 1,
        "ot_basis": "GROSS",
        "class_rates": [
            {"class_code": "8810", "rate_per_100_cents": 140},
        ],
        "max_payroll_per_executive_cents": 200000,
    },
    "MT": {
        "state_code": "MT",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
        "monopolistic": False,
        "per_capita_admin_fee_cents": 300,
        "expense_constant_cents": 20000,
        "min_payroll_threshold_cents": 5000,
        "state_minimum_premium_cents": 30000,
        "ot_basis": "NET",
        "class_rates": [
            {"class_code": "8810", "rate_per_100_cents": 100},
        ],
        "max_payroll_per_executive_cents": 250000,
    },
    "OH": {
        "state_code": "OH",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
        "monopolistic": True,
        "per_capita_admin_fee_cents": 0,
        "expense_constant_cents": 0,
        "min_payroll_threshold_cents": 0,
        "state_minimum_premium_cents": 0,
        "ot_basis": "GROSS",
        "class_rates": [
            {"class_code": "8810", "rate_per_100_cents": 100},
        ],
        "max_payroll_per_executive_cents": 250000,
    },
}

TEST_DEFAULTS = {
    "CLOCK_START": CLOCK_START,
    "POLICY_EFFECTIVE": "2026-09-01T00:00:00Z",
    "POLICY_EXPIRY": "2027-09-01T00:00:00Z",
}
