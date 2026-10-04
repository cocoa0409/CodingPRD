"""Domain thresholds and numeric constants from the PRD (§2.4, §2.7, §2.10, §3).

Every value below is pinned by PRD prose; keep parity with the PRD literals.
"""

# Logical clock (PRD §2.4): server-startup default, exactly this instant.
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

# Pricing constants (PRD §3.5/§3.6).
VOLUME_REBATE_PCT = 0.04          # volume factor 0.96 when tier is REBATE
SPECIALTY_SURCHARGE_PCT = 0.12    # specialty factor 1.12
PROVISIONAL_INDEX_LAG_MONTHS = 1  # provisional reads the prior-month index

# Early-termination exposure (PRD §3.2).
SHORTFALL_FEE_CENTS_PER_1000 = 400

# Spoilage expectation (PRD §3.5).
MAX_SPOILAGE_PCT = 0.15
SPECIALTY_SPOILAGE_PREMIUM_PCT = 0.03
CHANGEOVER_SPOILAGE_PENALTY_PCT = 0.02

# Scheduling (PRD §3.4, §3.8).
CHANGEOVER_BUFFER_MINUTES = 240
MAX_PICKUPS_PER_DAY = 2
MIN_RUN_QTY = 5000
MIN_COMMITTED_ANNUAL_UNITS = 1000000

# Forecast accuracy (PRD §3.7).
FORECAST_ROLLING_WINDOW = 3

# Plant posture (PRD §2.10).
CONGESTED_FREE_FRACTION = 0.20

# Reusable window literals (all at/after the clock start of 2026-09-01).
WIN_SEP_10 = ("2026-09-10T08:00:00Z", "2026-09-10T16:00:00Z")
WIN_SEP_11 = ("2026-09-11T08:00:00Z", "2026-09-11T16:00:00Z")
WIN_SEP_12 = ("2026-09-12T08:00:00Z", "2026-09-12T16:00:00Z")
