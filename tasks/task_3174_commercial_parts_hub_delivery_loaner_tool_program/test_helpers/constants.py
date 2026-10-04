"""Domain thresholds and constants from the PRD's calculation rules."""

# ---------------------------------------------------------------------------
# Pricing bands: discount_rate and promise_multiplier per tier band.
# ---------------------------------------------------------------------------
TIER_BANDS = {
    "BRONZE": {"discount_rate": 0.00, "promise_multiplier": 1.00},
    "SILVER": {"discount_rate": 0.05, "promise_multiplier": 0.80},
    "GOLD": {"discount_rate": 0.10, "promise_multiplier": 0.60},
    "PLATINUM": {"discount_rate": 0.15, "promise_multiplier": 0.50},
}

# ---------------------------------------------------------------------------
# Delivery fee schedule.
# ---------------------------------------------------------------------------
DELIVERY_FEE_CENTS = 795

# ---------------------------------------------------------------------------
# Source selection / promise clock.
# ---------------------------------------------------------------------------
SHOP_DELIVERY_RADIUS_MILES = 15
EXTENDED_RADIUS_MILES = 35
HUB_DELIVERY_MINUTES = 60
MEGA_HUB_DELIVERY_MINUTES = 90
CUTOFF_CUSHION = 120

# ---------------------------------------------------------------------------
# Order satisfaction.
# ---------------------------------------------------------------------------
BASE_FRACTION = 0.015
GROWTH_RATE = 0.20
SATURATION_CEILING = 1200

# ---------------------------------------------------------------------------
# Core credit and the refundable-deposit waterfall.
# ---------------------------------------------------------------------------
REFUNDABLE_RATE = 0.20
CORE_PORTION_RATE_A = 0.60
CORE_PORTION_RATE_B = 0.30
RESTOCKING_RATE = 0.15
DEPOSIT_FRACTION = 0.20

# ---------------------------------------------------------------------------
# Route run credit.
# ---------------------------------------------------------------------------
BASE_CENTS = 500
STANDARD_RATE_CENTS = 40
LONG_RUN_RATE_CENTS = 20
LONG_RUN_MILES = 40
OWNED_SHARE = 0.35
MIN_OWNED_CREDIT_CENTS = 150

# ---------------------------------------------------------------------------
# Replacement selection placement ranks.
# ---------------------------------------------------------------------------
FRONT_PLACEMENT_RANK = 1
REAR_LEFT_PLACEMENT_RANK = 1
REAR_RIGHT_PLACEMENT_RANK = 2
OTHER_PLACEMENT_RANK = 3

# ---------------------------------------------------------------------------
# Account posture aging.
# ---------------------------------------------------------------------------
AGING_GRACE_DAYS = 30

# ---------------------------------------------------------------------------
# Tool wear bands. Each threshold is the accumulated wear at which the band
# is reached; the companion values are the multiplier / forfeiture rate /
# grace period that band carries.
# ---------------------------------------------------------------------------
WEAR_BAND_THRESHOLDS = {
    "LEVEL_2": 25.0,
    "LEVEL_3": 45.0,
    "LEVEL_4": 65.0,
    "LEVEL_5": 85.0,
}

WEAR_BAND_VALUES = {
    "LEVEL_1": {"multiplier": 1.00, "forfeiture_rate": 0.00, "grace_hours": 48},
    "LEVEL_2": {"multiplier": 1.20, "forfeiture_rate": 0.40, "grace_hours": 36},
    "LEVEL_3": {"multiplier": 1.45, "forfeiture_rate": 0.60, "grace_hours": 24},
    "LEVEL_4": {"multiplier": 1.70, "forfeiture_rate": 0.80, "grace_hours": 18},
    "LEVEL_5": {"multiplier": 2.00, "forfeiture_rate": 1.00, "grace_hours": 12},
}

WEAR_INCREMENT_PER_RETURN = 0.4

# ---------------------------------------------------------------------------
# The logical clock.
# ---------------------------------------------------------------------------
STARTUP_DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
CAPACITY_EPOCH_STARTUP = "2026-09-01T00:00:00Z"

DEFAULT_CUTOFF_HOUR_LOCAL = 15
DEFAULT_CUTOFF_BUFFER_MINUTES = 30

# Convenience bundle used by fixtures.
THRESHOLDS = {
    "TIER_BANDS": TIER_BANDS,
    "DELIVERY_FEE_CENTS": DELIVERY_FEE_CENTS,
    "SHOP_DELIVERY_RADIUS_MILES": SHOP_DELIVERY_RADIUS_MILES,
    "EXTENDED_RADIUS_MILES": EXTENDED_RADIUS_MILES,
    "SATURATION_CEILING": SATURATION_CEILING,
    "REFUNDABLE_RATE": REFUNDABLE_RATE,
    "DEPOSIT_FRACTION": DEPOSIT_FRACTION,
    "LONG_RUN_MILES": LONG_RUN_MILES,
    "AGING_GRACE_DAYS": AGING_GRACE_DAYS,
    "WEAR_BAND_THRESHOLDS": WEAR_BAND_THRESHOLDS,
}

TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 5_000_000,
    "CREDIT_TERMS_DAYS": 30,
    "DELIVERY_RADIUS_MILES": 5.0,
    "PROMISE_TIME_MINUTES": 240,
    "DAILY_CAPACITY_UNITS": 500,
    "ON_HAND_UNITS": 20,
}