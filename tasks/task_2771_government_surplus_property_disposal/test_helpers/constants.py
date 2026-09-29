"""Domain thresholds and pinned numeric constants stated by the PRD."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict

# ─── Logical clock (PRD §2.4) ─────────────────────────────────────────────

CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ─── Fair market value (PRD §3.3) ────────────────────────────────────────

DEPRECIATION_RATE_PER_YEAR = Decimal("0.10")
FLOOR_AGE_FACTOR = Decimal("0.20")
NON_FUNCTIONAL_FACTOR = Decimal("0.60")
DAYS_PER_YEAR = 365
CONDITION_FACTOR: Dict[str, Decimal] = {
    "C1": Decimal("1.00"),
    "C2": Decimal("0.85"),
    "C3": Decimal("0.70"),
    "C4": Decimal("0.50"),
    "C5": Decimal("0.30"),
    "C6": Decimal("0.15"),
    "C7": Decimal("0.05"),
}

# ─── Screening (PRD §3.4) ────────────────────────────────────────────────

DE_MINIMIS_SCREENING_THRESHOLD_CENTS = 25_000
HOURS_PER_DAY = 24
SCREENING_TIER_ORDER = [
    "STATE_AGENCY",
    "LOCAL_GOVERNMENT",
    "ELIGIBLE_NONPROFIT",
    "PUBLIC_SALE",
]

# ─── Transfer pricing (PRD §3.5) ─────────────────────────────────────────

TIER_DISCOUNT: Dict[str, Decimal] = {
    "STATE_AGENCY": Decimal("0.25"),
    "LOCAL_GOVERNMENT": Decimal("0.50"),
    "ELIGIBLE_NONPROFIT": Decimal("0.10"),
}
HANDLING_TIER_1_CENTS = 100_000
HANDLING_TIER_2_CENTS = 1_000_000
HANDLING_FEE_SMALL_CENTS = 5_000
HANDLING_FEE_MEDIUM_CENTS = 12_500
HANDLING_FEE_LARGE_CENTS = 30_000

# ─── Federal use period (PRD §3.3) ───────────────────────────────────────

USE_PERIOD_MONTHS: Dict[str, int] = {
    "VEHICLE": 18,
    "HEAVY_EQUIPMENT": 18,
    "RESTRICTED_MILITARY": 18,
    "IT_EQUIPMENT": 12,
    "FURNITURE": 12,
}

# ─── Auction (PRD §3.6) ──────────────────────────────────────────────────

AUCTION_RESERVE_PCT = Decimal("0.60")
MIN_RESERVE_CENTS = 2_500
DEPOSIT_THRESHOLD_CENTS = 500_000
DEPOSIT_PCT = Decimal("0.10")
MIN_DEPOSIT_CENTS = 50_000
BID_INCREMENT_CENTS = 2_500
RELIST_COOLDOWN_HOURS = 24

# ─── Invoicing (PRD §3.7) ────────────────────────────────────────────────

PAYMENT_TERM_DAYS = 7

# ─── Proceeds distribution (PRD §3.9) ────────────────────────────────────

SERVICE_TIER_1_CENTS = 500_000
SERVICE_TIER_2_CENTS = 5_000_000
SERVICE_RATE_1 = Decimal("0.125")
SERVICE_RATE_2 = Decimal("0.0875")
SERVICE_RATE_3 = Decimal("0.0525")
SANITIZATION_FEE_CENTS = 7_500
DEMIL_FEE_CENTS = 22_500


def round_half_up(value) -> int:
    """Round a decimal quantity of cents to a whole cent, half away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ─── Canonical test values reused across scenarios ───────────────────────

TEST_DEFAULTS = {
    # A 2019 three-quarter ton pickup: C4 / functional / 185000 repair estimate
    # depreciates to a fair_market_value_cents of 297620.
    "PICKUP_COST_CENTS": 3_217_467,
    "PICKUP_ACQUISITION_DATE": "2019-03-15",
    "PICKUP_FMV_CENTS": 297_620,
    # A 2023 rack server: C2 / functional / no repair -> 985946.
    "SERVER_COST_CENTS": 1_449_920,
    "SERVER_ACQUISITION_DATE": "2023-11-02",
    "SERVER_FMV_CENTS": 985_946,
    # A 2020 road roller: C5 / non-functional -> 62669.
    "ROLLER_COST_CENTS": 870_401,
    "ROLLER_ACQUISITION_DATE": "2020-06-30",
    "ROLLER_FMV_CENTS": 62_669,
    # A 2024 furniture pallet: C6 / functional -> 12540, below de minimis.
    "FURNITURE_COST_CENTS": 104_500,
    "FURNITURE_ACQUISITION_DATE": "2024-05-20",
    "FURNITURE_FMV_CENTS": 12_540,
    "FURNITURE_RESERVE_CENTS": 7_524,
    # Venue rate card used by every auction scenario.
    "BUYER_PREMIUM_PCT": 0.105,
    "SALES_TAX_PCT": 0.0635,
}
