"""Domain thresholds — numeric constants from the PRD calculations and validations."""

# ─── Scale constants (PRD §2.7) ───────────────────────────────────────────────
MICROS_PER_SHARE = 1_000_000
MICROS_PER_CENT = 10_000
MICROS_TO_CENTS_DIVISOR = 10_000_000_000

# ─── Advisory fee ladder (PRD §3.6) ───────────────────────────────────────────
# (lower_cents, upper_cents, rate_bps); the last band has no upper bound.
ATTRIBUTABLE_TIERS = [
    (0, 250_000_000, 110),
    (250_000_001, 500_000_000, 90),
    (500_000_001, 1_000_000_000, 70),
    (1_000_000_001, None, 55),
]
PLATFORM_TIERS = [
    (0, 250_000_000, 8),
    (250_000_001, 500_000_000, 6),
    (500_000_001, 1_000_000_000, 4),
    (1_000_000_001, None, 3),
]
DAYS_PER_YEAR = 365

# ─── Alternative-asset haircut (PRD §3.5) ─────────────────────────────────────
HAIRCUT_BPS_YOUNG = 3500
HAIRCUT_BPS_AGED = 2500
AGE_THRESHOLD_DAYS = 270

# ─── Money movement (PRD §3.8) ────────────────────────────────────────────────
WITHHOLDING_RATE_BPS = 1000
JURISDICTION_WITHHOLDING_TYPES = ["IRA", "ROTH_IRA"]
ROUND_TRIP_EXPIRY_DAYS = 7

# ─── Listing cooldown (PRD §3.3) ──────────────────────────────────────────────
LISTING_COOLDOWN_SECONDS = 3600

# ─── Evidence correction rounds (PRD §2.11) ───────────────────────────────────
EVIDENCE_ROUND_CEILING = 4

# ─── Billing floors (PRD §3.7) ───────────────────────────────────────────────
MINIMUM_BILLABLE_BASIS_CENTS = 250_000_000
MAX_BILLING_PERIOD_DAYS = 400

# ─── Clock / period defaults used across fixtures ─────────────────────────────
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"
Q4_PERIOD_START = "2026-09-01T00:00:00Z"
Q4_PERIOD_END = "2026-12-01T00:00:00Z"
Q4_PERIOD_DAYS = 91


# ─── Thresholds dict mirroring the PRD-cited constants ────────────────────────
THRESHOLDS = {
    "MICROS_PER_SHARE": MICROS_PER_SHARE,
    "MICROS_PER_CENT": MICROS_PER_CENT,
    "MICROS_TO_CENTS_DIVISOR": MICROS_TO_CENTS_DIVISOR,
    "DAYS_PER_YEAR": DAYS_PER_YEAR,
    "HAIRCUT_BPS_YOUNG": HAIRCUT_BPS_YOUNG,
    "HAIRCUT_BPS_AGED": HAIRCUT_BPS_AGED,
    "AGE_THRESHOLD_DAYS": AGE_THRESHOLD_DAYS,
    "WITHHOLDING_RATE_BPS": WITHHOLDING_RATE_BPS,
    "ROUND_TRIP_EXPIRY_DAYS": ROUND_TRIP_EXPIRY_DAYS,
    "LISTING_COOLDOWN_SECONDS": LISTING_COOLDOWN_SECONDS,
    "EVIDENCE_ROUND_CEILING": EVIDENCE_ROUND_CEILING,
    "MINIMUM_BILLABLE_BASIS_CENTS": MINIMUM_BILLABLE_BASIS_CENTS,
    "MAX_BILLING_PERIOD_DAYS": MAX_BILLING_PERIOD_DAYS,
    "Q4_PERIOD_DAYS": Q4_PERIOD_DAYS,
}

TEST_DEFAULTS = {
    "VALUATION_PRICE_MICROS": 250_000_000,  # $250.00 per share
    "PERIOD_START": Q4_PERIOD_START,
    "PERIOD_END": Q4_PERIOD_END,
}


def round_half_up(numerator: int, denominator: int) -> int:
    """Round a rational to whole units, half up (the platform's single rounding rule)."""
    return (2 * numerator + denominator) // (2 * denominator)