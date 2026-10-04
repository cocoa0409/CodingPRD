"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # PRD §3.5: the cold-hold deadline is exactly four hours after the latest
    # all-clear condition report's reported_at.
    "COLD_HOLD_LIMIT_HOURS": 4,
    # PRD §2.6: the rolling shift-change interval is twelve hours, inclusive.
    "SHIFT_CHANGE_INTERVAL_HOURS": 12,
    # PRD §3.4: pre-positioning window is watch_started_at + 48 hours, inclusive.
    "PREPOSITION_WINDOW_HOURS": 48,
}

RELIEF = {
    # PRD §3.8 relief reimbursement constants.
    "MEAL_RATE_CENTS": 250,
    "TIER2_MIN_CENTS": 3000,
    "TIER3_MIN_CENTS": 8000,
    "TIER1_BONUS_CENTS": 0,
    "TIER2_BONUS_CENTS": 1000,
    "TIER3_BONUS_CENTS": 2500,
    "SHORTFALL_PENALTY_PER_MEAL_CENTS": 100,
    "TAX_BPS": 800,
}

CHECKLIST_KEYS = [
    "POWER_RESTORED",
    "WATER_POTABLE",
    "GAS_LEAK_CHECK",
    "FOOD_DISCARD_LOGGED",
    "CASH_DRAWER_COUNTED",
]

DEFAULT_CLOCK = "2026-09-10T08:00:00Z"

TEST_DEFAULTS = {
    "STORM_NAME": "Hurricane Delta",
    "UNIT_CODE": "U-1",
    "UNIT_ADDRESS": "1 Storm Way",
    "RELIEF_ORG_NAME": "Red Shield Relief",
    "RELIEF_ORG_EMAIL": "ops@redshield.example",
    "CREW_FULL_NAME": "Jo Vega",
    "TRAVEL_ORIGIN": "Atlanta",
    "NIGHTLY_RATE_CENTS": 9000,
}
