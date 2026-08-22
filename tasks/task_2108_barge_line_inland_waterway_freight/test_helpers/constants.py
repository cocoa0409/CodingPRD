"""Domain thresholds and canonical scenario values taken from the PRD."""

# --- Logical clock (PRD §2.5) ---------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"      # value before any reposition
CLOCK_REFERENCE = "2026-08-02T00:00:00Z"    # while reference data is laid down
CLOCK_ACTIVATION = "2026-08-05T00:00:00Z"   # while contracts are activated
CLOCK_CLAIM_WINDOW = "2026-08-22T00:00:00Z"  # inside the 30-day claim window
CLOCK_CLAIM_EXPIRED = "2026-09-25T00:00:00Z"  # past the 30-day claim window

# --- River stage bands (PRD §3.2) -----------------------------------------
BAND_MAX_DRAFT_FEET = {
    "HIGH_WATER": 12.0,
    "NORMAL": 12.0,
    "LOW": 10.5,
    "CRITICAL": 9.0,
}
BAND_TOW_SIZE_CAP = {
    "HIGH_WATER": 20,
    "NORMAL": 40,
    "LOW": 30,
    "CRITICAL": 6,
}
STAGE_HIGH_WATER_FLOOR = 25.0
STAGE_NORMAL_FLOOR = 15.0
STAGE_LOW_FLOOR = 8.0

# --- Cleaning (PRD §3.1, §3.4) --------------------------------------------
CLEANLINESS_RANK = {"DIRTY": 0, "SWEPT": 1, "WASHED": 2, "STEAM_CERTIFIED": 3}
REQUIRED_LEVEL_RANK = {"NONE": 0, "SWEEP": 1, "WASH": 2, "STEAM_CERT": 3}
CLEANLINESS_LEVEL_TO_STATUS = {
    "NONE": "DIRTY",
    "SWEEP": "SWEPT",
    "WASH": "WASHED",
    "STEAM_CERT": "STEAM_CERTIFIED",
}
CLEANING_FEE_CENTS = {"NONE": 0, "SWEEP": 45_000, "WASH": 180_000, "STEAM_CERT": 420_000}
DEFAULT_REQUIRED_LEVEL = "WASH"

# --- Fleeting (PRD §3.4) ---------------------------------------------------
SECONDS_PER_DAY = 86_400
MIN_BILLABLE_DAYS = 1

# --- Lock scheduling and delay (PRD §3.6) ---------------------------------
MIN_CUT_COUNT = 1
LOCK_CLOSURE_DELAY_MINUTES = 240
TOW_DELAY_STATUS_MINUTES = 120
CONTRACT_DELAY_PROTECTION_MINUTES = 150
CONTRACT_DELAY_PROTECTION_LAYTIME_HOURS = 12

# --- Draft profile (PRD §3.5) ---------------------------------------------
INCHES_PER_FOOT = 12

# --- Billing (PRD §3.8) ----------------------------------------------------
NOTICE_GRACE_HOURS = 6
REBATE_TIERS = [
    {"subtotal_floor_cents": 0, "pct": 0.0},
    {"subtotal_floor_cents": 1_000_000, "pct": 0.015},
    {"subtotal_floor_cents": 5_000_000, "pct": 0.03},
]

# --- Cargo claims (PRD §3.9) ----------------------------------------------
TRADE_TOLERANCE_PCT = 0.005
CLAIM_FILING_WINDOW_DAYS = 30
MAX_CLAIM_REVISION_ROUNDS = 2

# --- Canonical GRAIN scenario values used by the composite fixtures --------
GRAIN_TARIFF_CODE = "T-GRAIN-2026"
GRAIN_BASE_RATE = 1.2378
GRAIN_MIN_CHARGE_CENTS = 250_000
GRAIN_DEMURRAGE_RATE_CENTS_PER_HOUR = 32_500
FUEL_SURCHARGE_TABLE = [
    {"threshold_cents_per_gallon": 200, "pct": 0.0},
    {"threshold_cents_per_gallon": 300, "pct": 0.045},
    {"threshold_cents_per_gallon": 400, "pct": 0.09},
    {"threshold_cents_per_gallon": 500, "pct": 0.145},
]
DEFAULT_GAUGE_STATION = "MEMPHIS"
DEFAULT_STAGE_FEET = 18.0
DEFAULT_READING_AT = "2026-08-02T06:00:00Z"
DEFAULT_DIESEL_POSTING_DATE = "2026-08-03"
DEFAULT_DIESEL_PRICE = 300
DEFAULT_FUEL_PCT = 0.045
DEFAULT_CREDIT_LIMIT_CENTS = 900_000_000

# Standard voyage instants used across the movement fixtures.
DEPARTED_AT = "2026-08-14T12:00:00Z"
TOW_ARRIVED_AT = "2026-08-20T04:00:00Z"

# Per-cut discharge timetable (PRD §3.7 laytime clocks).
STANDARD_DISCHARGES = [
    {
        "arrived_at": "2026-08-20T06:00:00Z",
        "unload_started_at": "2026-08-20T18:00:00Z",
        "unload_finished_at": "2026-08-21T14:00:00Z",
        "discharged_tons": 1687,
    },
    {
        "arrived_at": "2026-08-20T08:00:00Z",
        "unload_started_at": "2026-08-21T02:00:00Z",
        "unload_finished_at": "2026-08-21T09:30:00Z",
        "discharged_tons": 1643,
    },
]

TEST_DEFAULTS = {
    "CAPACITY_TONS": 1750,
    "LIGHT_DRAFT_FEET": 1.5,
    "TONS_PER_INCH_IMMERSION": 17.0,
    "LOADED_TONS": 1700,
    "LAYTIME_HOURS": 12,
    "DECLARED_VALUE_CENTS_PER_TON": 22_000,
    "ORIGIN_MILE": 600,
    "DESTINATION_MILE": 200,
}
