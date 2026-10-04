"""Domain thresholds and shared constants from the PRD's calculation rules."""

# Logical clock default reading (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Sizing thresholds (PRD §3.1).
MIN_FIRMING_DURATION_HOURS = 4.00
MIN_ARBITRAGE_DURATION_HOURS = 2.00

# Spare-parts credit pool share of the annual fee (PRD §3.6).
SPARE_PARTS_POOL_PCT = 0.30

# Augmentation planning penalty and floor (PRD §3.5).
AUGMENTATION_PENALTY = 0.005
AUGMENTATION_CAPACITY_FLOOR_MWH = 80.0

# Auto-created augmentation event window length in days (PRD §3.5).
AUTO_AUGMENTATION_WINDOW_DAYS = 30

# Per-cycle degradation rates by (market_application, duty_cycle_profile).
DEGRADATION_RATES = {
    "ENERGY_ARBITRAGE": {
        "ONE_CYCLE_DAILY": 0.0006,
        "TWO_CYCLES_DAILY": 0.0012,
        "CONTINUOUS": 0.0015,
    },
    "FREQUENCY_REGULATION": {
        "ONE_CYCLE_DAILY": 0.0004,
        "TWO_CYCLES_DAILY": 0.0008,
        "CONTINUOUS": 0.0010,
    },
    "CAPACITY_FIRMING": {
        "ONE_CYCLE_DAILY": 0.0005,
        "TWO_CYCLES_DAILY": 0.0010,
        "CONTINUOUS": 0.0012,
    },
}

# Pagination (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
