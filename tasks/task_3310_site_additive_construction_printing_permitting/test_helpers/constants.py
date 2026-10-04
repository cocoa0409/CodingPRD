"""Domain thresholds — numeric constants from the PRD (§3)."""

# Logical clock default before any clock-set call (PRD §2.4).
CLOCK_START_UTC = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Permit fee schedule (PRD §3.10).
    "BASE_PERMIT_FEE_CENTS": 250000,
    "PER_M2_FEE_CENTS": 4500,
    "AM_SURCHARGE_CENTS": 175000,
    "AM_RESUBMIT_MARKUP_PCT": 0.10,
    "MAX_AM_REVIEW_ROUNDS": 3,
    # Foundation cure window (PRD §3.2).
    "FOUNDATION_CURE_HOURS": 72,
    # Material batch gating (PRD §3.5).
    "SLUMP_TOLERANCE_MM": 15,
    "PUMP_WINDOW_A": (40, 60),
    "PUMP_WINDOW_B": (55, 75),
    "PUMP_WINDOW_C": (30, 50),
    "WC_RATIO_MIN": 0.30,
    "WC_RATIO_MAX": 0.60,
    # Weather print-permissibility (PRD §3.6).
    "WEATHER_OBSERVATION_VALID_MIN": 30,
    "AIR_TEMP_MIN_C": 4,
    "AIR_TEMP_MAX_C": 38,
    "HUMIDITY_MAX_PCT": 90,
    "WIND_MAX_MPS": 12,
    # Interruption cure windows by mix code (PRD §3.7).
    "CURE_PENALTY_WINDOW_MIN": 10,
    "HARD_INTERRUPTION_CAP_MIN": 60,
    "MAX_INTERRUPTION_MIN_A": 30,
    "MAX_INTERRUPTION_MIN_B": 20,
    "MAX_INTERRUPTION_MIN_C": 45,
    # Layer inspection thresholds (PRD §3.8).
    "BOND_MIN_MPA": 1.5,
    "DIM_TOL_MM": 6,
    # Learning curve (PRD §3.9).
    "BASELINE_WINDOW": 3,
    "ROLLING_WINDOW": 3,
    "LAYER_PRINT_MIN_PER_LAYER": 8,
}

TEST_DEFAULTS = {
    "PLAN_AREA_M2": 80,
    "WALL_THICKNESS_MM": 200,
    "WALL_HEIGHT_MM": 3000,
    "RAIL_SPAN_MM": 10000,
    "LEVELING_TOLERANCE_MM": 5.0,
    "MEASURED_DEVIATION_MM": 3.0,
    "TARGET_SLUMP_MM": 100,
    "TOTAL_LAYERS_PLANNED": 30,
    "AM_REVIEW_DAYS": 30,
}
