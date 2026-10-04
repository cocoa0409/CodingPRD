"""Domain thresholds and constants from the PRD calculations (§2.9, §3).

The server's logical clock starts at exactly 2026-09-01T00:00:00Z (PRD §2.4);
every fixture date below is reachable from that default.
"""

# Logical clock (PRD §2.4)
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# effective_power_cost / monthly_power_settlement (PRD §3.3)
INTERRUPTIBLE_DISCOUNT_PCT = 0.25
LOSS_FACTOR = 1.037

# curtailment_margin_gate (PRD §3.5)
ALUMINA_RATIO_T_PER_T = 1.92
POWER_INTENSITY_MWH_PER_T = 13.5
OTHER_CONVERSION_COST_PER_T = 420.0
RESTART_RESERVE_PER_T = 150.0

# restart_cost class schedule (PRD §3.6)
RESTART_CREW_COST_PER_DAY = 15000
WARM_THRESHOLD_HOURS = 24
COLD_THRESHOLD_HOURS = 720
RESTART_CLASS_SCHEDULE = {
    "HOT": {"base": 80000, "per_tpd": 40, "per_idle_day": 0},
    "WARM": {"base": 350000, "per_tpd": 120, "per_idle_day": 2500},
    "COLD": {"base": 1800000, "per_tpd": 400, "per_idle_day": 6000},
}

# hedge_coverage (PRD §3.5, §3.7)
HEDGE_MIN_COVERAGE = 0.5
MONTHLY_CAPACITY_FACTOR = 30

# product_mix_margin (PRD §3.9)
BILLET_CONVERSION_PER_T = 180.0
SLAB_CONVERSION_PER_T = 220.0
VALUE_ADDED_CONVERSION_PER_T = 350.0

# Common contract window covering the default clock (used by fixtures)
DEFAULT_WINDOW_START = "2026-01-01T00:00:00Z"
DEFAULT_WINDOW_END = "2027-01-01T00:00:00Z"

# Standard blended component stack (FIXED 150 @ 32.00, MARKET 100, INTERRUPTIBLE 50 cap 500h)
BLENDED_COMPONENTS = [
    {"component_type": "FIXED", "volume_mw": 150, "fixed_price_per_mwh": 32.00},
    {"component_type": "MARKET_INDEXED", "volume_mw": 100},
    {"component_type": "INTERRUPTIBLE", "volume_mw": 50, "interruptible_cap_hours_per_year": 500},
]

FIXED_ONLY_COMPONENTS = [
    {"component_type": "FIXED", "volume_mw": 150, "fixed_price_per_mwh": 32.00},
]

TEST_DEFAULTS = {
    "SMELTER_NAME": "Riverbend",
    "REGION": "NA_NORTHWEST",
    "RATED_CAPACITY_TPD": 1000,
    "LABOR_HEADCOUNT": 450,
    "SUPPLIER_NAME": "Bonneville",
    "LINE_CODE": "P1",
    "POTLINE_CAPACITY_TPD": 500,
    "AMPERAGE_KA": 320,
    "UNION_NAME": "USW-2026",
    "SEVERANCE_WEEKS_PER_YEAR": 1.5,
}
