"""Domain constants and rounding helpers transcribed from the PRD.

Nothing here is invented: every literal is a number the PRD states in prose,
and every helper reproduces a rounding convention the PRD names explicitly
(round half up for monetary products, integer floor for day, month and
per-unit-revenue figures).
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Union

# --------------------------------------------------------------------------
# Envelope / pagination (PRD section 2.3)
# --------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10

# --------------------------------------------------------------------------
# Logical clock (PRD section 2.4)
# --------------------------------------------------------------------------

#: The value the logical clock reads at server startup.
SERVER_START_CLOCK = "2026-08-01T00:00:00.000Z"

#: The instant scenarios reposition the clock to before building a world.
BASE_CLOCK = "2026-01-01T00:00:00Z"
BASE_CLOCK_STAMP = "2026-01-01T00:00:00.000Z"

SECONDS_PER_DAY = 86400
DAYS_PER_DEPRECIATION_MONTH = 30

# --------------------------------------------------------------------------
# Fleet plan posture (PRD section 3.3)
# --------------------------------------------------------------------------

BASIS_POINT_SCALE = 10000
POSTURE_RESTRICTED_FLOOR_BP = 9000
POSTURE_FROZEN_FLOOR_BP = 10000

# --------------------------------------------------------------------------
# Redistribution pricing (PRD section 3.6)
# --------------------------------------------------------------------------

SURCHARGE_TIER_1_CEILING_CENTS = 50000
SURCHARGE_TIER_2_CEILING_CENTS = 150000
SURCHARGE_RATE_TIER_1 = Decimal("0.12")
SURCHARGE_RATE_TIER_2 = Decimal("0.08")
SURCHARGE_RATE_TIER_3 = Decimal("0.05")
TRANSPORT_HANDLING_FLAT_CENTS = 7500
TRANSFER_PAYBACK_DAYS = 45
MAX_ORDER_REVISION_COUNT = 3

# --------------------------------------------------------------------------
# Prep scheduling (PRD section 3.4)
# --------------------------------------------------------------------------

PREP_BAY_BUFFER_MINUTES = 60

# --------------------------------------------------------------------------
# Damage, recovery and total loss (PRD section 3.7)
# --------------------------------------------------------------------------

TOTAL_LOSS_RATIO_NUMERATOR = 7000
TOTAL_LOSS_RATIO_SCALE = 10000
RECOVERY_CAP_FACTOR = Decimal("1.25")

# --------------------------------------------------------------------------
# Remarketing (PRD section 3.8)
# --------------------------------------------------------------------------

FLOOR_PRICE_FACTOR = Decimal("0.75")
RECONDITION_LOADING_FACTOR = Decimal("1.075")
TRANSPORT_TO_HUB_LOADING_FACTOR = Decimal("1.15")
RECONDITION_PLANNING_PCT = Decimal("0.02")

# --------------------------------------------------------------------------
# Plan performance (PRD section 3.9)
# --------------------------------------------------------------------------

SEASON_DAYS: Dict[str, int] = {
    "PEAK": 92,
    "SHOULDER": 122,
    "OFF_PEAK": 151,
}

# --------------------------------------------------------------------------
# Rounding helpers
# --------------------------------------------------------------------------

Number = Union[int, float, Decimal, str]


def round_half_up(value: Number) -> int:
    """Round a monetary product to whole cents, half away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value: Number) -> float:
    """Round a utilization fraction to four decimal places, half up."""
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def floor_div(numerator: int, denominator: int) -> int:
    """Integer division truncated toward zero, as the PRD's per-unit rule."""
    return int(Decimal(numerator) / Decimal(denominator)) if denominator else 0


def money_times(amount: int, factor: Number) -> int:
    """A cents amount multiplied by a fractional factor, rounded half up."""
    return round_half_up(Decimal(amount) * Decimal(str(factor)))


def surcharge_rate_for_base_haul(base_haul_cents: int) -> Decimal:
    """Select the fuel surcharge rate from the base haul alone."""
    if base_haul_cents < SURCHARGE_TIER_1_CEILING_CENTS:
        return SURCHARGE_RATE_TIER_1
    if base_haul_cents < SURCHARGE_TIER_2_CEILING_CENTS:
        return SURCHARGE_RATE_TIER_2
    return SURCHARGE_RATE_TIER_3


def estimated_transport_cost(distance_km: int, origin_rate_cents_per_km: int) -> int:
    """Base haul plus surcharge plus handling flat, per PRD section 3.6."""
    base_haul = distance_km * origin_rate_cents_per_km
    surcharge = money_times(base_haul, surcharge_rate_for_base_haul(base_haul))
    return base_haul + surcharge + TRANSPORT_HANDLING_FLAT_CENTS


def transport_to_hub_cost(hub_distance_km: int, rate_cents_per_km: int) -> int:
    """Hub distance times the market rate times 1.15, rounded half up."""
    return money_times(hub_distance_km * rate_cents_per_km, TRANSPORT_TO_HUB_LOADING_FACTOR)


def fill_ratio_bp(allocated: int, planned: int) -> int:
    """Fill ratio in basis points as an integer floor."""
    return floor_div(allocated * BASIS_POINT_SCALE, planned)


def posture_for(allocated: int, planned: int) -> str:
    """Derive posture from the fill ratio, per PRD section 3.3."""
    ratio = fill_ratio_bp(allocated, planned)
    if ratio >= POSTURE_FROZEN_FLOOR_BP:
        return "FROZEN"
    if ratio >= POSTURE_RESTRICTED_FLOOR_BP:
        return "RESTRICTED"
    return "OPEN"


def total_loss_required(estimate_cents: int, net_book_value_at_report_cents: int) -> bool:
    """Pure integer cross-multiplication ratio test, per PRD section 3.7."""
    return (
        estimate_cents * TOTAL_LOSS_RATIO_SCALE
        >= net_book_value_at_report_cents * TOTAL_LOSS_RATIO_NUMERATOR
    )


# --------------------------------------------------------------------------
# Identifiers guaranteed not to resolve. The framework exposes one; the
# numbered variants let a single test walk several endpoints at once and keep
# the failures distinguishable.
# --------------------------------------------------------------------------

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

UNKNOWN_UUIDS = [
    "00000000-0000-4000-8000-000000000001",
    "00000000-0000-4000-8000-000000000002",
    "00000000-0000-4000-8000-000000000003",
    "00000000-0000-4000-8000-000000000004",
    "00000000-0000-4000-8000-000000000005",
    "00000000-0000-4000-8000-000000000006",
    "00000000-0000-4000-8000-000000000007",
    "00000000-0000-4000-8000-000000000008",
    "00000000-0000-4000-8000-000000000009",
    "00000000-0000-4000-8000-00000000000a",
    "00000000-0000-4000-8000-00000000000b",
    "00000000-0000-4000-8000-00000000000c",
    "00000000-0000-4000-8000-00000000000d",
]
