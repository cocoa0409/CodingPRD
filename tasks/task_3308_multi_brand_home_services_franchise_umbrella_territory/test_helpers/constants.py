"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # PRD 2.13: the logical clock's startup default.
    "CLOCK_START": "2026-09-01T00:00:00Z",
    # PRD 2.6 / 3.2: the franchisor protected-household cap per franchisee.
    "HOUSEHOLD_CAP": 250000,
    # PRD 2.10 / 3.8: weighted score bands, inclusive at the bottom of each band.
    "AUDIT_PASS_MIN": 85.0,
    "AUDIT_WATCH_MIN": 70.0,
    # PRD 3.8: weighted-score inputs and precision.
    "ANNOUNCED_WEIGHT": 1.00,
    "MYSTERY_SHOP_WEIGHT": 0.80,
    "CRITICAL_PENALTY_PER_FINDING": 7.5,
    "WEIGHTED_SCORE_DP": 1,
    # PRD 2.7 / 3.8: remediation window in logical hours (168 == 7 logical days).
    "STANDARDS_REMEDIATION_HOURS": 168,
    # PRD 3.8: audit reopen window in logical hours.
    "AUDIT_REOPEN_HOURS": 24,
    # PRD 3.5: referral expiry window in logical hours.
    "REFERRAL_EXPIRY_HOURS": 168,
    # PRD 3.6: allocation hold window in logical hours.
    "ALLOCATION_HOLD_HOURS": 26,
    # PRD 3.7: renewal window, in days ahead of expires_on.
    "RENEWAL_WINDOW_DAYS": 90,
    # PRD 3.4: labor charge constants.
    "HOURLY_RATE_CENTS": {"EMERGENCY": 18500, "URGENT": 18500, "STANDARD": 14500},
    "PRIORITY_HOURS_SCALE": {"EMERGENCY": 0.5, "URGENT": 0.75, "STANDARD": 1.0},
    "SOURCE_MULTIPLIER": {
        "NATIONAL_ACCOUNT": 0.90,
        "PROPERTY_MANAGER": 0.95,
        "CALL_CENTER_LEAD": 1.00,
        "CROSS_BRAND_REFERRAL": 0.85,
        "DIRECT": 1.00,
    },
    # PRD 3.6: lead cost constants.
    "BAND_BASE_CENTS": {
        "BAND_1": 2500, "BAND_2": 4000, "BAND_3": 6500, "BAND_4": 9000,
    },
    "VALUE_UNIT_CENTS": 100000,
    "VALUE_UNIT_RATE_CENTS": 250,
    "MULTI_BRAND_MIN": 3,
    "MULTI_BRAND_DISCOUNT": 0.85,
    # PRD 2.3: pagination defaults and bounds.
    "PAGE_DEFAULT_LIMIT": 10,
    "PAGE_MIN_LIMIT": 1,
    "PAGE_MAX_LIMIT": 100,
    "PAGE_DEFAULT_OFFSET": 0,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "CLOCK_DAY_1": "2026-09-02T00:00:00Z",
    "CLOCK_DAY_7": "2026-09-08T00:00:00Z",
    "CLOCK_DAY_8": "2026-09-09T00:00:00Z",
    "PERIOD_START": "2026-09-01T00:00:00Z",
    "PERIOD_END": "2026-10-01T00:00:00Z",
    "SIGNED_ON": "2026-09-01T00:00:00Z",
    "TERM_MONTHS": 120,
    "ROYALTY_RATE": 0.06,
    "AD_FUND_RATE": 0.01,
    "AUDIT_CYCLE_MONTHS": 12,
    "HOUSEHOLD_COUNT": 30000,
    "EXPANSION_RIGHT_HOUSEHOLDS": 40000,
    "REVIEWER_OPERATOR": "op-reviewer-macon",
    "APPROVER_OPERATOR": "op-approver-quill",
    "AUDITOR_OPERATOR": "op-auditor-riley",
}