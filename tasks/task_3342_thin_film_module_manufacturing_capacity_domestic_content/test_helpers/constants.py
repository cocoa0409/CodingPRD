"""Domain thresholds — numeric constants from PRD §3 calculations."""

# Logical clock (PRD §2.4): startup default, never wall-clock.
LOGICAL_CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
LOGICAL_CLOCK_DEFAULT_YEAR = 2026

# Deposit requirement (PRD §3.4): tier fractions of contract value.
TIER_DEPOSIT_FRACTION = {
    "TIER_A": 0.05,
    "TIER_B": 0.10,
    "TIER_C": 0.20,
}

# Deposit forfeiture waterfall (PRD §3.4).
PERFORMANCE_FLOOR = 0.80
FORFEIT_RATE = 0.15

# Ramp yield curve (PRD §3.2).
YIELD_FLOOR = 0.60
YIELD_CAP = 0.95
RAMP_RATE = 0.30
RAMP_EXIT = 0.85
RAMP_EXIT_MIN_QUARTER_INDEX = 2

# Domestic content qualification (PRD §3.7).
PRINTED_MIN = 0.40
MANUFACTURED_PRODUCTS_MIN = 0.40
ADJUSTMENT_USD = 4.0

# Warranty (PRD §3.8).
GUARANTEED_KWH_PER_KW = 1700.0
LIQUIDATED_RATE_PER_KWH = 0.05
WARRANTY_CAP_FRACTION = 0.10

# Recycling recovery (PRD §3.9).
RECOVERY_MIN_PCT = 0.90

# Bin energy model (PRD §3.3).
PERFORMANCE_RATIO = 0.85
HOURS_YEAR = 8760
ENERGY_SCALE = 0.001


def required_deposit_usd(contracted_mw: float, price_usd_per_w: float,
                         credit_tier: str) -> float:
    """required = contracted_mw * 1e6 * price * tier_fraction (PRD §3.4)."""
    return contracted_mw * 1_000_000.0 * price_usd_per_w * TIER_DEPOSIT_FRACTION[credit_tier]


def guaranteed_energy_kwh(claimed_mw: float) -> float:
    """guaranteed = round(claimed_mw * 1000 * 1700.0, 2) (PRD §3.8)."""
    return round(claimed_mw * 1000.0 * GUARANTEED_KWH_PER_KW, 2)


def warranty_cap_mw(annual_capacity_mw: float) -> float:
    """cap = 0.10 * annual_capacity_mw (PRD §3.8)."""
    return WARRANTY_CAP_FRACTION * annual_capacity_mw
