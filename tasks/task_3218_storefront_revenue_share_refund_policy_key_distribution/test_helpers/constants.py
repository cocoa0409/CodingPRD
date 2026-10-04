"""Domain thresholds and shared helpers — numeric constants from the PRD."""
import math
from decimal import ROUND_HALF_UP, Decimal

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

TIER1_RATE = 0.30
TIER2_RATE = 0.25
TIER3_RATE = 0.20
TIER2_THRESHOLD = 1_000_000_000   # $10,000,000 in cents
TIER3_THRESHOLD = 5_000_000_000   # $50,000,000 in cents

FX = {"EUR": 0.92, "GBP": 0.79, "JPY": 149.50, "BRL": 5.05}
PPP = {"EUR": 0.90, "GBP": 0.95, "JPY": 0.70, "BRL": 0.50}
MAX_DEVIATION_BPS = 2500

PURCHASE_AGE_LIMIT_DAYS = 14
PLAYTIME_LIMIT_MINUTES = 120

RESTRICT_THRESHOLD = 3
ABUSE_WINDOW_DAYS = 60
OVER_LIMIT_PENALTY = 3

FREE_KEY_BASE = 5000

BOMB_MIN_COUNT = 10
BOMB_RATIO = 0.80
BOMB_WINDOW_DAYS = 7
DETECTION_WINDOW_HOURS = 24

POSITIVE_THRESHOLD = 0.70
MIXED_THRESHOLD = 0.40
RECENT_WINDOW_DAYS = 30

REDEEM_ACCOUNT_LIMIT = 3
REDEEM_GLOBAL_LIMIT = 50
REDEEM_WINDOW_MINUTES = 60


def round_half_up(value) -> int:
    """Round to the nearest integer, ties (and any .5+ fraction) rounding up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recommended_cents(base_price_usd_cents: int, currency: str) -> int:
    """Recommended regional price: base * FX * PPP, rounded half-up."""
    return round_half_up(base_price_usd_cents * FX[currency] * PPP[currency])


def usd_recognized_for(gross_cents: int, currency: str) -> int:
    """USD-recognized value of a purchase's gross in the given currency."""
    if currency == "USD":
        return gross_cents
    return round_half_up(gross_cents / FX[currency])


def expected_tier(recognized_usd_cents: int) -> int:
    """Descending inclusive-threshold tier scan."""
    if recognized_usd_cents >= TIER3_THRESHOLD:
        return 3
    if recognized_usd_cents >= TIER2_THRESHOLD:
        return 2
    return 1


def review_weight(playtime_minutes: int) -> int:
    """Weight of a review: floor of sqrt(playtime), minimum 1."""
    return max(1, int(math.sqrt(playtime_minutes)))
