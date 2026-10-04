"""Domain thresholds — numeric constants from PRD calculations (§2.6, §3)."""

THRESHOLDS = {
    # PRD §3.3: close requires received_tons >= 80 percent of committed_tons.
    "SETTLEMENT_MIN_FILL_PCT": 0.80,
    # PRD §3.4: furnace tap grid excludes non-terminal heats within 45 minutes.
    "FURNACE_GRID_MINUTES": 45,
    # PRD §3.10: at least 15 minutes between released_at and the next called_at.
    "EVENT_MIN_GAP_MINUTES": 15,
    # PRD §3.5: blend benchmark per ton for the scrap surcharge credit.
    "BENCHMARK_CENTS_PER_TON": 40000,
    # PRD §3.11: the profit share rate is 0.10.
    "PROFIT_SHARE_RATE": 0.10,
    # PRD §3.2: moisture fraction inclusive upper bound.
    "MOISTURE_PCT_MAX": 0.30,
    # PRD §3.2: lot chemistry range caps.
    "CU_LOT_CAP": 0.005,
    "MN_LOT_CAP": 0.02,
    # PRD §2.3: pagination bounds.
    "PAGE_LIMIT_DEFAULT": 10,
    "PAGE_LIMIT_MAX": 100,
}

TEST_DEFAULTS = {
    "CLOCK_SEED": "2026-09-10T00:00:00Z",
    "MILL_NAME": "Test Mill",
    "FURNACE_CAPACITY_TONS": 150,
    "CASTER_RATE_TPH": 80,
}
