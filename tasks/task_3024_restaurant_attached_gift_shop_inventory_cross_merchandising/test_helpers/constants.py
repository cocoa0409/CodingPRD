"""Domain thresholds — numeric constants named in the PRD's arithmetic rules."""

# --------------------------------------------------------------------------
# Revenue recognition
# --------------------------------------------------------------------------
SALE_STAGING_FACTOR = 0.36
PROVISIONAL_DIVISOR = 7
FINAL_DIVISOR = 3

# --------------------------------------------------------------------------
# Combined check service fee — marginal bands
# --------------------------------------------------------------------------
BAND_LOW_CENTS = 4000
BAND_MID_CENTS = 8000
BAND_HIGH_CENTS = 12000
BAND_PCTS = [0.00, 0.15, 0.18, 0.20]

# Brand defaults (PRD §3.7)
DEFAULT_LIQUIDATION_TRIGGER_RPG_CENTS = 700
DEFAULT_OPEN_RECEIPT_GRACE_HOURS = 24
DEFAULT_TRANSFER_VARIANCE_TOLERANCE_BPS = 200
DEFAULT_WAITING_AREA_RETAIL_WEIGHT_BPS = 6000
DEFAULT_TIP_MINIMUM_MINUTES = 240
DEFAULT_CLEARANCE_BUFFER_HOURS = 24
DEFAULT_FOOD_STORAGE_CORRIDOR_UNITS = 40
DEFAULT_MAX_CHECK_TOTAL_CENTS = 50000
DEFAULT_CLEARANCE_MAX_ACTIVE = 3

# --------------------------------------------------------------------------
# Waiting-area conversion index
# --------------------------------------------------------------------------
DECAY_PER_TRANSACTION = 0.10
DECAY_CAP = 0.50
WEIGHT_TOTAL_BPS = 10000

# --------------------------------------------------------------------------
# Retail sales per guest
# --------------------------------------------------------------------------
EMPTY_SET_VALUE = 0

# --------------------------------------------------------------------------
# Clearance cadence
# --------------------------------------------------------------------------
STAGE_MARKDOWN_PCT = {"S1": 0.25, "S2": 0.40, "S3": 0.55, "S4": 0.70}
STAGE_SEQUENCE = ["S1", "S2", "S3", "S4"]
WEEK_FACTORS = [1.00, 0.95, 0.88, 0.78, 0.70]
DEFAULT_WEEK_FACTOR = 0.70

# --------------------------------------------------------------------------
# Liquidation waterfall
# --------------------------------------------------------------------------
LIQUIDATION_TIER_SHARES = [0.40, 0.30, 0.30]
LIQUIDATION_TIER_RATES = [0.90, 0.70, 0.55]

# --------------------------------------------------------------------------
# Import planning
# --------------------------------------------------------------------------
WEEKS_DEMAND_HORIZON = 4
WEEK_DEMAND_CENTS = 300000
SEASON_START_WEEK = {
    "HARVEST": 38,
    "WINTER_HOLIDAY": 40,
    "SPRING": 10,
    "SUMMER": 26,
    "NOSTALGIA_CLASSIC": 1,
}
MARGIN_FLOOR_PCT = 0.30

# --------------------------------------------------------------------------
# Planogram region fit
# --------------------------------------------------------------------------
PROFILE_MULTIPLIER = {"FULL": 1.00, "REGIONAL_TWEAK": 1.25, "MINIMAL": 0.55}
DRIFT_BPS_GATE = 15000
REGIONAL_TWEAK_BONUS = 4
LOCAL_EVENT_BONUS = 1
REGION_TARGET_SLOTS = 18

# --------------------------------------------------------------------------
# Store-day thresholds
# --------------------------------------------------------------------------
RUSH_GUEST_THRESHOLD = 120
STEADY_GUEST_THRESHOLD = 40

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
CLOCK_START_UTC = "2026-09-01T00:00:00Z"