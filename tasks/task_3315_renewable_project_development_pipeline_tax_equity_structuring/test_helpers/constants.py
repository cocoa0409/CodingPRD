"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # PRD: the base price floor on offtake execution.
    "PRICE_FLOOR_USD_MWH": 20.00,
    # PRD: five-percent safe-harbor test.
    "SAFE_HARBOR_PCT": 0.05,
    # PRD: safe-harbor confirm window from order creation.
    "SAFE_HARBOR_WINDOW_DAYS": 183,
    # PRD: four-year continuity window (inclusive of one leap day).
    "FOUR_YEAR_WINDOW_DAYS": 1461,
    # PRD: max consecutive work gap under facts-and-circumstances.
    "MAX_WORK_GAP_DAYS": 365,
    # PRD: cure window after a continuity lapse.
    "CURE_WINDOW_DAYS": 90,
    # PRD: ITC rates.
    "BASE_RATE_PCT": 30.00,
    "DOMESTIC_CONTENT_ADDER_PCT": 10.00,
    "ENERGY_COMMUNITY_ADDER_PCT": 10.00,
    # PRD: waterfall investor shares.
    "PRE_FLIP_INVESTOR_PCT": 99.00,
    "POST_FLIP_INVESTOR_PCT": 5.00,
    # PRD: debt conversion gates.
    "MIN_DSCR": 1.30,
    "MAX_ADVANCE_RATE": 0.80,
    # PRD: operations handoff liquidated damages.
    "LD_PER_POINT_USD": 25000,
    "LD_CAP_USD": 500000.00,
    # PRD: default operations handoff guarantee.
    "DEFAULT_AVAILABILITY_GUARANTEE_PCT": 97.0,
    # PRD: study window conflict buffer.
    "STUDY_BUFFER_DAYS": 5,
}

# PRD: the logical clock reads exactly this before any set call.
CLOCK_INITIAL_UTC = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "BUDGET": 1000000.00,
    "PERIOD_END_DATE": "2027-03-31T00:00:00Z",
    "DELIVERY_START_DATE": "2028-01-01T00:00:00Z",
}
