"""Domain thresholds — numeric constants from the PRD's pricing and timing rules."""

# PRD §2.4: the logical clock starts at 2026-09-01T00:00:00Z on server startup.
DEFAULT_LOGICAL_START = "2026-09-01T00:00:00Z"

# PRD §3.6: base prices per issue category, in whole cents.
BASE_PRICE_BY_ISSUE_CENTS = {
    "SCREEN_DAMAGE": 19900,
    "BATTERY": 6900,
    "WATER_DAMAGE": 39900,
    "SOFTWARE": 4900,
    "HARDWARE_OTHER": 29900,
}

# PRD §3.6: devices older than two years add a 15% age surcharge.
AGE_SURCHARGE_RATE = 0.15
AGE_THRESHOLD_YEARS = 2
DAYS_PER_YEAR = 365.25

# PRD §3.6: premium models multiply (base + age surcharge) by 1.25.
PREMIUM_MODELS = ["IPHONE_15_PRO", "IPHONE_15_PRO_MAX", "MACBOOK_PRO_16"]
PREMIUM_MODEL_MULTIPLIER = 1.25

# PRD §3.4: triage scoring weights and same-day threshold.
PART_WEIGHT = {
    "DISPLAY": 3,
    "BATTERY": 2,
    "LOGIC_BOARD": 5,
    "CAMERA": 2,
    "ENCLOSURE": 1,
    "OTHER": 1,
}
SAME_DAY_THRESHOLD = 0.8

# PRD §3.3: appointment slot rules.
SLOT_BUFFER_MINUTES = 10
CHECK_IN_EARLY_MINUTES = 15
BOOKING_HORIZON_DAYS = 30

# PRD §3.5: pending verifications expire 24 hours after creation.
VERIFICATION_EXPIRY_HOURS = 24

# PRD §3.8: repeat escalation window.
REPEAT_WINDOW_DAYS = 90

# PRD §3.6: depot shipping.
BASE_SHIPPING_CENTS = 1500
ZONE_MULTIPLIER = {"ZONE_1": 1.0, "ZONE_2": 1.5, "ZONE_3": 2.0}
