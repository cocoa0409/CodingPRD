"""Domain thresholds and constants named in the PRD's calculations."""
from typing import Optional

# Product uplift applied to an overshoot to produce the capped impact.
PRODUCT_UPLIFT = 1.2

# The hedge is suspended (a member product is priced under the cap) below this
# hedged share rate.
HEDGE_SUSPEND_THRESHOLD = 0.50

# Deposit attribution window, in days.
FREEZE_WINDOW_DAYS = 14

# Notification cooldown and BUY_NOW warranty windows, in hours.
COOLDOWN_HOURS = 6
BUY_NOW_WINDOW_HOURS = 24

# The rate metric's divisor when a protected cancellation consumes flights-at-fare.
CONTINUUM_DIVISOR = 1.25

# Change products are priced at this rate rather than the route's base rate.
CHANGE_PRODUCT_RATE = 0.35
CHANGE_FEE_RATE = 0.10

# Clamp applied to a client-declared cancellation disruption probability.
PROB_FLOOR = 0.01
PROB_CEIL = 0.95

# Bonus-day bands on the effective destruction band of the clamped declaration.
BAND_SPLIT_PROBABILITY = 0.05
BAND_STANDARD_PROBABILITY = 0.10

# The duration metric is free up to this many days, then linear with this divisor.
DURATION_FREE_DAYS = 3
DURATION_LINEAR_DIVISOR = 2

# Membership overrun multiplier applied to the deposit.
FORFEITURE_MULTIPLIER = 2

THRESHOLDS = {
    "PRODUCT_UPLIFT": PRODUCT_UPLIFT,
    "HEDGE_SUSPEND_THRESHOLD": HEDGE_SUSPEND_THRESHOLD,
    "FREEZE_WINDOW_DAYS": FREEZE_WINDOW_DAYS,
    "COOLDOWN_HOURS": COOLDOWN_HOURS,
    "BUY_NOW_WINDOW_HOURS": BUY_NOW_WINDOW_HOURS,
    "CONTINUUM_DIVISOR": CONTINUUM_DIVISOR,
    "CHANGE_PRODUCT_RATE": CHANGE_PRODUCT_RATE,
    "CHANGE_FEE_RATE": CHANGE_FEE_RATE,
    "PROB_FLOOR": PROB_FLOOR,
    "PROB_CEIL": PROB_CEIL,
    "BAND_SPLIT_PROBABILITY": BAND_SPLIT_PROBABILITY,
    "BAND_STANDARD_PROBABILITY": BAND_STANDARD_PROBABILITY,
    "DURATION_FREE_DAYS": DURATION_FREE_DAYS,
    "DURATION_LINEAR_DIVISOR": DURATION_LINEAR_DIVISOR,
    "FORFEITURE_MULTIPLIER": FORFEITURE_MULTIPLIER,
    # Insurance tier boundaries.
    "TIER_1_BOUNDARY_CENTS": 20000,
    "TIER_2_BOUNDARY_CENTS": 50000,
    "TIER_3_BOUNDARY_CENTS": 100000,
    "TIER_4_BOUNDARY_CENTS": 200000,
    # Deposit range.
    "DEPOSIT_MIN_CENTS": 100,
    "DEPOSIT_MAX_CENTS": 5000,
    # Payment amount ceiling.
    "PAYMENT_MAX_CENTS": 20000,
    # Region cap on bound coverage dates.
    "POOL_REGION_CAP_POSITIONS": 4,
    # A lapsed position's region is revived below this resolved pool.
    "POOL_REVIVAL_THRESHOLD_CENTS": 250000,
}

TEST_DEFAULTS = {
    "REGION": "WEST",
    "BASE_FARE_CENTS": 8900,
    "TIP_FAIR_CENTS": 9000,
    "DEPOSIT_CENTS": 250,
    "DISCLOSURE_HEADLINE": "Fare products are optional and separate from the ticket",
    "CURVE_EACH_DAY_PRICES_CENTS": [8200, 9000, 9600, 11200, 12800],
    "CURVE_SEATS_LEFT_AT_EACH_DAY": [9, 8, 6, 4, 2],
    "DEPARTURE_DATE": "2026-10-01T00:00:00Z",
    "CLOCK_DEFAULT": "2026-09-01T00:00:00Z",
    # Route defaults a caller may omit.
    "TRAVEL_CLASS": "ECO",
    "VOLATILITY_INDEX": 0.20,
    "HEDGE_RATIO_PCT": 0.60,
    "MAX_GUARANTEE_EXPOSURE_CENTS": 50000,
    "DEFAULT_DISRUPTION_PROBABILITY": 0.25,
    "DISRUPTION_SEVERITY_INDEX": 0.1429,
    "PROTECTION_BASE_RATE": 0.25,
    "PROTECTION_FLOOR_RATE": 0.20,
    "CANCEL_MINIMUM_DISRUPTION": 0.30,
    "PEAK_PRICE_DAY_INDEX": 0,
    "SEATS_LEFT": 9,
}


def insurance_tier_ceiling(amount_cents: int) -> int:
    """Map a money amount to its insurance tier ceiling.

    The comparisons are strict, so an amount of exactly 200000 cents maps to
    200000 rather than 300000.
    """
    if amount_cents < 20000:
        return 30000
    if amount_cents < 50000:
        return 50000
    if amount_cents < 100000:
        return 100000
    if amount_cents < 200000:
        return 200000
    return 300000


def round_half_up(value: float, places: int = 2) -> float:
    """Round half up, matching the API's money rounding convention."""
    from decimal import Decimal, ROUND_HALF_UP

    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def expected_cap_cents(manifest_fare_cents: int) -> int:
    """cap_cents is the manifest fare multiplied by 1.4 and rounded half-up."""
    return int(round_half_up(manifest_fare_cents * 1.4))


def expected_capped_impact_cents(overshoot_cents: int) -> float:
    """capped_impact_cents is the overshoot multiplied by 1.2 and rounded half-up."""
    return round_half_up(overshoot_cents * PRODUCT_UPLIFT)


def duration_metric(days: int) -> int:
    """The duration metric: free up to three days, linear with divisor 2 after."""
    if days <= 0:
        return 0
    if days <= 3:
        return days
    return 3 + -(-(days - 3) // DURATION_LINEAR_DIVISOR)  # ceil((days - 3) / 2)


def rate_metric_days(premium_cents: int, disruption_fare_cents: int) -> int:
    """A protected cancellation consumes ceil(premium / disruption fare) days."""
    if disruption_fare_cents <= 0:
        return 0
    return -(-premium_cents // disruption_fare_cents)  # integer ceiling


def clamp_probability(value: float) -> float:
    """Clamp a client-declared probability into [0.01, 0.95]."""
    return min(max(value, PROB_FLOOR), PROB_CEIL)


def bonus_days_from_band(clamped_probability: float) -> int:
    """Standalone bonus days are 0, 1 or 2 from the clamped declaration's band."""
    if clamped_probability < BAND_SPLIT_PROBABILITY:
        return 0
    if clamped_probability < BAND_STANDARD_PROBABILITY:
        return 1
    return 2
