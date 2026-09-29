"""Domain thresholds and derived-arithmetic helpers taken from the PRD's calculations."""
from decimal import Decimal, ROUND_HALF_UP

# --- Verification (PRD §3.3) ------------------------------------------------
VERIFICATION_WINDOW_MONTHS = 3
VERIFICATION_TOLERANCE = Decimal("0.05")          # inclusive: 0.0500 passes

# --- Valuation tiers and age bands (PRD §3.4) -------------------------------
TIER_LOWER_BOUNDARY_CENTS = 30_000                # first tier strictly below
TIER_UPPER_BOUNDARY_CENTS = 100_000               # third tier from here upward
BASE_MULTIPLE_LOW = Decimal("9.0")
BASE_MULTIPLE_MID = Decimal("10.0")
BASE_MULTIPLE_HIGH = Decimal("11.0")
AGE_BAND_ADD_FULL_TURN_MONTHS = 60                # >= 60 months: +1.0
AGE_BAND_ADD_HALF_TURN_FROM = 36                  # 36..59 months: +0.5
AGE_BAND_NEUTRAL_FROM = 24                        # 24..35 months: +0.0
AGE_BAND_SUBTRACT_AT_OR_BELOW = 23                # <= 23 months: -1.0
EFFECTIVE_MULTIPLE_FLOOR = Decimal("6.0")
EFFECTIVE_MULTIPLE_CAP = Decimal("12.0")
REPAIR_MULTIPLE = Decimal("3.0")

# --- Negotiation and acceptance (PRD §3.5) ----------------------------------
MIN_DOWN_PAYMENT_PCT = {
    "CASH": Decimal("1.00"),
    "SELLER_NOTE": Decimal("0.30"),
    "BANK_LOAN": Decimal("0.20"),
    "SBA": Decimal("0.10"),
}
RETENTION_GUARANTEE_MIN_DAYS = 60
RETENTION_GUARANTEE_MAX_DAYS = 365
HOLDBACK_PCT = Decimal("0.15")
HOLDBACK_CAP_CENTS = 200_000

# --- Diligence sign-off (PRD §3.6) ------------------------------------------
VERIFIED_MRR_FLOOR_PCT = Decimal("0.70")          # of listing.listed_mrr_cents
REPRICE_THRESHOLD_PCT = Decimal("0.90")           # of deal.current_offer_price_cents

# --- Introductions and closing (PRD §3.8) -----------------------------------
INTRODUCTION_WINDOW_DAYS = 45                     # half-open from accepted_on
MAX_INTRODUCTIONS_PER_DATE = 2
ROUTE_DAY_RANK = {"MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5}
REPLACEMENT_GRACE_DAYS = 14                       # after guarantee_end_utc

# --- Commission ladder (PRD §3.8) -------------------------------------------
COMMISSION_TIER_MID_CENTS = 1_500_000
COMMISSION_TIER_HIGH_CENTS = 4_000_000
COMMISSION_RATE_LOW = Decimal("0.10")
COMMISSION_RATE_MID = Decimal("0.08")
COMMISSION_RATE_HIGH = Decimal("0.06")
COMMISSION_FLOOR_CENTS = 50_000

# --- Retention guarantee and clawback (PRD §3.9) ---------------------------
CLAWBACK_CAP_PCT = Decimal("0.20")                # of current_offer_price_cents
ALLOWANCE_PCT = Decimal("0.05")                   # of guaranteed_mrr_cents
REPLACEMENT_CREDIT_CAP_PCT = Decimal("0.50")
SOLICITATION_PENALTY_FACTOR = Decimal("1.5")

# --- Clock (PRD §2.5) -------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Licensing regime bounds (PRD §3.1) ------------------------------------
TRANSFER_PROCESSING_DAYS_MIN = 1
TRANSFER_PROCESSING_DAYS_MAX = 180
COOLING_OFF_DAYS_MIN = 0
COOLING_OFF_DAYS_MAX = 180
PERMIT_TYPES = ["PESTICIDE_APPLICATOR", "CONTRACTOR", "BUSINESS_TAX"]

# --- Pagination (PRD §2.3) --------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


def round_half_up_cents(value) -> int:
    """Round a fractional cent amount half up to a whole cent (PRD §2.6)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_ratio(value) -> Decimal:
    """Round a ratio to four decimal places, half up (PRD §2.6)."""
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def ratio_4dp(numerator: int, denominator: int) -> Decimal:
    """Four-decimal ratio with the PRD's half-up rule; 0.0000 on a zero denominator."""
    if denominator == 0:
        return Decimal("0.0000")
    return round_half_up_ratio(Decimal(numerator) / Decimal(denominator))


def pct_of_cents(amount_cents: int, pct: Decimal) -> int:
    """A percentage of a cent amount, rounded half up to whole cents."""
    return round_half_up_cents(Decimal(amount_cents) * pct)


def base_multiple_for(recurring_mrr_cents: int) -> Decimal:
    """Select the tiered base multiple from the recurring base alone (PRD §3.4)."""
    if recurring_mrr_cents < TIER_LOWER_BOUNDARY_CENTS:
        return BASE_MULTIPLE_LOW
    if recurring_mrr_cents < TIER_UPPER_BOUNDARY_CENTS:
        return BASE_MULTIPLE_MID
    return BASE_MULTIPLE_HIGH


def age_adjustment_for(weighted_age_months: int) -> Decimal:
    """The age adjustment applied to the base multiple (PRD §3.4)."""
    if weighted_age_months >= AGE_BAND_ADD_FULL_TURN_MONTHS:
        return Decimal("1.0")
    if weighted_age_months >= AGE_BAND_ADD_HALF_TURN_FROM:
        return Decimal("0.5")
    if weighted_age_months >= AGE_BAND_NEUTRAL_FROM:
        return Decimal("0.0")
    return Decimal("-1.0")


def effective_multiple_for(recurring_mrr_cents: int, weighted_age_months: int) -> Decimal:
    """Base multiple plus age adjustment, clamped to [6.0, 12.0] at one decimal."""
    adjusted = base_multiple_for(recurring_mrr_cents) + age_adjustment_for(weighted_age_months)
    clamped = min(max(adjusted, EFFECTIVE_MULTIPLE_FLOOR), EFFECTIVE_MULTIPLE_CAP)
    return clamped.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def commission_for(gross_cents: int) -> int:
    """The five-step commission ladder: tier from the gross, round, then floor."""
    if gross_cents < COMMISSION_TIER_MID_CENTS:
        rate = COMMISSION_RATE_LOW
    elif gross_cents < COMMISSION_TIER_HIGH_CENTS:
        rate = COMMISSION_RATE_MID
    else:
        rate = COMMISSION_RATE_HIGH
    raw_fee = round_half_up_cents(Decimal(gross_cents) * rate)
    return max(raw_fee, COMMISSION_FLOOR_CENTS)


def holdback_for(price_cents: int) -> int:
    """Fifteen percent of the price rounded half up first, then capped at 200,000."""
    return min(pct_of_cents(price_cents, HOLDBACK_PCT), HOLDBACK_CAP_CENTS)
