"""Domain thresholds - numeric constants from the PRD's calculation rules."""

# --- hot-market capacity commitment (§3.2) ---
MAJOR_MARKET_DEMAND_UNITS = 100000
REGIONAL_DEMAND_UNITS = 25000
PROBABILITY_FLOOR = 0.05
RUSH_HOURS = 6
RUSH_ADDITIONAL_FACTOR = 1.5
SAME_HOUR_FACTOR = 2.0
TIER_RESIDUAL_LOCAL = 25
TIER_RESIDUAL_REGIONAL = 50
TIER_RESIDUAL_MAJOR_MARKET = 0

# --- licensor royalty accrual (§3.8) ---
SKU_ROYALTY_RATE = {
    "JERSEY": 0.08,
    "TRACTOR": 0.02,
    "DUFFEL": 0.04,
    "CAP": 0.06,
    "MINI": 0.06,
    "PENNANT": 0.00,
}
DESIGNER_PREMIUM_PCT = 0.125

# --- rush delivery commitment (§3.4) ---
RUSH_WINDOW_HOURS = 24
STANDARD_WINDOW_HOURS = 72
RUSH_WEIGHT = 0.9
STANDARD_WEIGHT = 0.1

# --- licensor minimum-guarantee settlement (§3.9) ---
GUARANTEE_BLOCK_CAP_CENTS = 12500

# --- counterfeit exposure (§3.10) ---
EXPOSURE_VALUATION_CENTS_PER_UNIT = 1450
LEAKAGE_RATE_OF_GROSS = 0.6
DETERRENCE_MULTIPLIER = 2.5
CONFIRMED_FLOOR_CENTS = 500

# --- wholesale fulfillment total (§3.5) ---
CHANNEL_RATE_CENTS_PER_UNIT = {
    "VENUE_RETAIL": 12,
    "EVENT_POPUP": 9,
    "ECOM": 5,
}
RUSH_SURCHARGE_CENTS_PER_UNIT = 2
DONATION_FLAT_CENTS = 100
DESTROY_PENALTY_CENTS_PER_UNIT = 4
DONATE_PENALTY_CENTS_PER_UNIT = 0

# --- demand-collapse write-down (§3.7) ---
STANDARD_RECOVERY_PCT = 0.6
FULL_LOSS_RECOVERY_PCT = 0.0
WRITE_DOWN_RESET_HOURS = 48
POST_EVENT_MARKUP = 2.5

# --- event window (§2.6) ---
EVENT_WINDOW_HOURS = 48

# --- test defaults ---
TEST_DEFAULTS = {
    "CLOCK_EPOCH": "2026-09-01T00:00:00Z",
    "UNIT_COST_CENTS": 900,
    "DEMAND_QTY": 5000,
    "ROYALTY_RATE_PCT": 0.1,
    "MINIMUM_GUARANTEE_CENTS": 100000,
}


def ceil_units(value: float) -> int:
    """Round up to the next whole unit."""
    import math
    return int(math.ceil(round(value, 9)))


def floor_units(value: float) -> int:
    """Round down to the whole unit."""
    import math
    return int(math.floor(round(value, 9)))


def round_half_up(value: float, places: int = 2) -> float:
    """Round half up to `places` decimal places, on decimal arithmetic."""
    from decimal import Decimal, ROUND_HALF_UP
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))