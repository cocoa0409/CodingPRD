"""Domain thresholds — numeric constants from PRD calculation sections."""

THRESHOLDS = {
    # Fleet selector (PRD §3.5)
    "BATTERY_MIN_DISPATCH": 20,
    "CYCLE_PENALTY": 1,
    # Travel cost (PRD §3.3)
    "PLAN_CONGESTION_WEIGHT": 0.10,
    "EXEC_CONGESTION_WEIGHT": 0.25,
    "CONGESTION_CAP": 3,
    "DETOUR_FLAT": 4,
    # Stow placement (PRD §3.4)
    "NEW_SLOT_ACCESS_BASE": 3,
    # Workload smoothing (PRD §3.3)
    "LATENESS_WEIGHT": 5,
    "DISRUPTION_WEIGHT": 2,
    "FATIGUE_WEIGHT": 1,
    "STATION_BASE_RATE_SECONDS": 120,
    # Charge credit tiers (PRD §3.5)
    "RATE_T1": 0.5,
    "RATE_T2": 0.3,
    "RATE_T3": 0.1,
    "TIER1_MINUTES": 30,
    "TIER2_MINUTES": 90,
    # Maintenance (PRD §3.5)
    "MAINTENANCE_CYCLE_THRESHOLD": 5,
    "MAINT_BUFFER_MINUTES": 15,
    # Throughput projection (PRD §3.8)
    "PICKS_PER_PICKER_HOUR": 120,
    "UNITS_PER_TRIP": 6,
    "TRIPS_PER_HOUR": 4,
    "HOURS_IN_SHIFT": 8,
}

# Default logical clock at server start (PRD §2.4): 2026-09-01T00:00:00Z
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "ZONE_MAX_HUMAN_OCCUPANCY": 2,
    "POD_SLOT_CAPACITY": 5,
    "STATION_MAX_QUEUE": 5,
    "CHARGER_SLOT_COUNT": 2,
    "DEFAULT_CUTOFF": "2026-09-02T00:00:00Z",
}
