"""Constants, rounding and the seven calculation rules (PRD 2.6 and 3.x)."""

from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# unit conversions
# ---------------------------------------------------------------------------
OZ_PER_BBL = Decimal("3968")
OZ_PER_GAL = Decimal("128")

BBL_PER_UNIT = {
    "HALF_BBL_KEG": Decimal("0.500"),
    "QUARTER_BBL_KEG": Decimal("0.250"),
    "CAN_CASE_24": Decimal("0.073"),
}

POUR_OZ = {
    "SAMPLE_4OZ": Decimal("4"),
    "HALF_PINT_8OZ": Decimal("8"),
    "PINT_16OZ": Decimal("16"),
    "CROWLER_32OZ": Decimal("32"),
    "GROWLER_64OZ": Decimal("64"),
}

GROWLER_CONTAINERS = ("CROWLER_32OZ", "GROWLER_64OZ")
DRAFT_CONTAINERS = ("SAMPLE_4OZ", "HALF_PINT_8OZ", "PINT_16OZ")
GROWLER_ONLY_FIELDS = (
    "container_sanitized",
    "sanitizer_ppm",
    "contact_time_seconds",
    "attested_by_user_id",
    "label_fields",
)

# ---------------------------------------------------------------------------
# sanitation
# ---------------------------------------------------------------------------
SANITIZER_MIN_PPM = 150
SANITIZER_MAX_PPM = 400
SANITATION_MIN_CONTACT_SECONDS = 60

# ---------------------------------------------------------------------------
# cellar / keg
# ---------------------------------------------------------------------------
TANK_CIP_BUFFER_HOURS = 12
BATCH_CLOSE_REMAINDER_BBL = Decimal("1.000")
KEG_SHRINKAGE_TOLERANCE_PCT = Decimal("0.02")
KEG_SIZES = (Decimal("0.5"), Decimal("0.25"))

# ---------------------------------------------------------------------------
# excise
# ---------------------------------------------------------------------------
FED_TIER1_LIMIT_BBL = Decimal("60000")
FED_TIER1_RATE_CENTS_PER_BBL = Decimal("350")
FED_TIER2_RATE_CENTS_PER_BBL = Decimal("1600")
STATE_TAPROOM_RATE_CENTS_PER_BBL = Decimal("1085")
STATE_DISTRIBUTION_RATE_CENTS_PER_BBL = Decimal("870")
SMALL_BREWER_STATE_CREDIT_PCT = Decimal("0.50")
SMALL_BREWER_STATE_CREDIT_LIMIT_BBL = Decimal("15000")

# ---------------------------------------------------------------------------
# landed cost
# ---------------------------------------------------------------------------
FREIGHT_PER_MILE_CENTS = Decimal("30")
FREIGHT_PER_BBL_CENTS = Decimal("1200")
FREIGHT_DISCOUNT_TIERS = (
    (Decimal("400000"), Decimal("0.30")),
    (Decimal("200000"), Decimal("0.20")),
    (Decimal("100000"), Decimal("0.10")),
)
FRANCHISE_FEE_PCT = Decimal("0.03")

# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------
MAX_CONCURRENT_OFFSITE_PERMITS_PER_STATE = 2
EVENT_ANNUAL_BBL_CAP_PER_STATE = Decimal("25.00")

ZERO_BBL = Decimal("0.000")
ZERO_OZ = Decimal("0.00")


# ---------------------------------------------------------------------------
# rounding
# ---------------------------------------------------------------------------

def _q(places):
    if places == 0:
        return Decimal("1")
    return Decimal(1).scaleb(-places)


def round_half_up(value, places):
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(_q(places), rounding=ROUND_HALF_UP)


def bbl(value):
    return round_half_up(value, 3)


def bbl2(value):
    return round_half_up(value, 2)


def oz(value):
    return round_half_up(value, 2)


def cents(value):
    return int(round_half_up(value, 0))


# ---------------------------------------------------------------------------
# sanitation verdict
# ---------------------------------------------------------------------------

def sanitation_passes(sanitizer_ppm, contact_time_seconds):
    in_band = SANITIZER_MIN_PPM <= sanitizer_ppm <= SANITIZER_MAX_PPM
    long_enough = contact_time_seconds >= SANITATION_MIN_CONTACT_SECONDS
    return bool(in_band and long_enough)


# ---------------------------------------------------------------------------
# landed cost
# ---------------------------------------------------------------------------

def landed_cost(bbl_requested, price_per_bbl_cents, distance_miles, channel):
    product_cents = cents(Decimal(bbl_requested) * Decimal(price_per_bbl_cents))
    freight_raw = (cents(Decimal(distance_miles) * FREIGHT_PER_MILE_CENTS)
                   + cents(Decimal(bbl_requested) * FREIGHT_PER_BBL_CENTS))
    pct = Decimal("0")
    for threshold, tier_pct in FREIGHT_DISCOUNT_TIERS:
        if Decimal(product_cents) >= threshold:
            pct = tier_pct
            break
    discount = cents(Decimal(freight_raw) * pct)
    freight_cents = freight_raw - discount
    subtotal = product_cents + freight_cents
    if channel == "WHOLESALER":
        franchise_fee_cents = cents(Decimal(subtotal) * FRANCHISE_FEE_PCT)
    else:
        franchise_fee_cents = 0
    return {
        "product_cents": product_cents,
        "freight_cents": freight_cents,
        "franchise_fee_cents": franchise_fee_cents,
        "landed_cost_cents": product_cents + freight_cents + franchise_fee_cents,
    }


# ---------------------------------------------------------------------------
# excise tax
# ---------------------------------------------------------------------------

def excise_tax(taproom_bbl, distribution_bbl, ytd_bbl_before_period):
    total_bbl = bbl(Decimal(taproom_bbl) + Decimal(distribution_bbl))
    headroom = FED_TIER1_LIMIT_BBL - Decimal(ytd_bbl_before_period)
    tier1 = min(total_bbl, headroom)
    if tier1 < 0:
        tier1 = Decimal("0")
    tier2 = bbl(total_bbl - tier1)
    federal = (cents(tier1 * FED_TIER1_RATE_CENTS_PER_BBL)
               + cents(tier2 * FED_TIER2_RATE_CENTS_PER_BBL))
    state_raw = (cents(Decimal(taproom_bbl) * STATE_TAPROOM_RATE_CENTS_PER_BBL)
                 + cents(Decimal(distribution_bbl) * STATE_DISTRIBUTION_RATE_CENTS_PER_BBL))
    if Decimal(ytd_bbl_before_period) + total_bbl <= SMALL_BREWER_STATE_CREDIT_LIMIT_BBL:
        state_tax = cents(Decimal(state_raw) * (Decimal("1") - SMALL_BREWER_STATE_CREDIT_PCT))
    else:
        state_tax = state_raw
    return {
        "federal_tax_cents": federal,
        "state_tax_cents": state_tax,
        "total_tax_due_cents": federal + state_tax,
        "total_bbl": total_bbl,
    }


# ---------------------------------------------------------------------------
# keg depletion variance
# ---------------------------------------------------------------------------

def depletion_variance(returned_volume_gal, filled_volume_oz, poured_volume_oz):
    returned_oz = oz(Decimal(returned_volume_gal) * OZ_PER_GAL)
    expected_oz = oz(Decimal(filled_volume_oz) - Decimal(poured_volume_oz))
    variance = oz(returned_oz - expected_oz)
    tolerance = oz(KEG_SHRINKAGE_TOLERANCE_PCT * Decimal(filled_volume_oz))
    flagged = abs(variance) > tolerance
    return returned_oz, variance, bool(flagged)
