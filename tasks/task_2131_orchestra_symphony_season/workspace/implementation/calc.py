"""Calculation rules (PRD 2.5, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8).

Every monetary quantity is an integer number of cents; every rate is in basis
points where 10000 == 1.00x.  Scaling a monetary amount by a basis-point figure
divides by 10000 and rounds half up.
"""

from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

DEMAND_MULTIPLIER_BP = {"LOW": 9000, "MODERATE": 10000, "HIGH": 11500, "PEAK": 13000}
DONOR_DISCOUNT_BP = {"NONE": 0, "FRIEND": 250, "SUSTAINER": 500,
                     "BENEFACTOR": 1000, "LAUREATE": 1500}
PRICE_FLOOR_BP = 8500
PRICE_CEILING_BP = 12000

DONOR_POINTS = {"NONE": 0, "FRIEND": 50, "SUSTAINER": 150,
                "BENEFACTOR": 400, "LAUREATE": 900}

DONOR_THRESHOLDS = (
    ("LAUREATE", 5000000),
    ("BENEFACTOR", 2500000),
    ("SUSTAINER", 1000000),
    ("FRIEND", 250000),
)

LOYALTY_CAP_BP = 2000

AD_SIZE_RATE_CENTS = {"FULL_PAGE": 120000, "HALF_PAGE": 70000, "QUARTER_PAGE": 40000}
PLACEMENT_FEE_BP = {"BACK_COVER": 2500, "INSIDE_FRONT_COVER": 1500, "RUN_OF_BOOK": 0}


def round_half_up(numerator, denominator=10000):
    """Exact integer-cent division with the round-half-up rule."""
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def scale_bp(amount_cents, bp):
    return round_half_up(amount_cents * bp, 10000)


# --------------------------------------------------------------------------
# demand band / fill
# --------------------------------------------------------------------------

def fill_bp_of(taken, capacity):
    """Truncated-downward basis points of occupancy; 0 when nothing is taken."""
    if taken <= 0 or capacity <= 0:
        return 0
    return (taken * 10000) // capacity


def demand_band_of(fill_bp):
    if fill_bp >= 8000:
        return "PEAK"
    if fill_bp >= 5000:
        return "HIGH"
    if fill_bp >= 2000:
        return "MODERATE"
    return "LOW"


# --------------------------------------------------------------------------
# calculations.single_ticket_dynamic_price
# --------------------------------------------------------------------------

def single_ticket_price(base_ticket_price_cents, price_multiplier_bp,
                        held_count, sold_count, capacity, donor_level=None,
                        seat_count=1):
    """Returns (unit_price_cents, demand_band, fill_bp, donor_discount_bp,
    amount_due_cents).  Rounding order is pinned: section multiplier first,
    then the demand multiplier, then the donor discount, clamp last."""
    taken = held_count + sold_count
    fill_bp = fill_bp_of(taken, capacity)
    band = demand_band_of(fill_bp)
    demand_multiplier_bp = DEMAND_MULTIPLIER_BP[band]

    raw_unit = round_half_up(base_ticket_price_cents * price_multiplier_bp, 10000)
    priced = round_half_up(raw_unit * demand_multiplier_bp, 10000)
    donor_discount_bp = DONOR_DISCOUNT_BP[donor_level] if donor_level else 0
    discounted = round_half_up(priced * (10000 - donor_discount_bp), 10000)

    floor_unit = round_half_up(raw_unit * PRICE_FLOOR_BP, 10000)
    ceiling_unit = round_half_up(raw_unit * PRICE_CEILING_BP, 10000)
    unit_price_cents = min(ceiling_unit, max(floor_unit, discounted))

    return (unit_price_cents, band, fill_bp, donor_discount_bp,
            unit_price_cents * seat_count)


# --------------------------------------------------------------------------
# calculations.subscription_package_price
# --------------------------------------------------------------------------

def package_discount_bp(concert_count):
    if concert_count >= 8:
        return 1500
    if concert_count >= 5:
        return 1000
    if concert_count >= 3:
        return 500
    return 0


def subscription_price(locked_unit_price_cents, seat_count, concert_count,
                       loyalty_bp=None):
    """Step 2 sums the already-rounded per-concert lines, step 3 applies the
    package discount tier, step 4 applies loyalty (RENEWAL only)."""
    subtotal = 0
    for _ in range(concert_count):
        subtotal += locked_unit_price_cents * seat_count
    after_package = round_half_up(subtotal * (10000 - package_discount_bp(concert_count)), 10000)
    if loyalty_bp is None:
        return after_package
    return round_half_up(after_package * (10000 - loyalty_bp), 10000)


def loyalty_discount_bp(season_loyalty_bp, consecutive_renewal_years):
    return min(LOYALTY_CAP_BP, season_loyalty_bp + 100 * consecutive_renewal_years)


# --------------------------------------------------------------------------
# calculations.musician_service_settlement
# --------------------------------------------------------------------------

def premium_bp(agreement, musician, doubling_count):
    """Three additive terms, never compounded."""
    total = 0
    if musician["is_principal"]:
        total += agreement["principal_premium_bp"]
    total += musician["overscale_bp"]
    total += doubling_count * agreement["doubling_premium_bp"]
    return total


def base_pay_cents(agreement, musician, doubling_count):
    bp = premium_bp(agreement, musician, doubling_count)
    return round_half_up(agreement["scale_service_fee_cents"] * (10000 + bp), 10000)


def overtime_minutes_of(worked_minutes, max_service_minutes):
    return max(0, worked_minutes - max_service_minutes)


def final_pay_cents(base_pay, overtime_minutes, overtime_rate_cents_per_minute):
    """Overtime is a flat per-minute rate, never scaled by the premium."""
    return base_pay + overtime_minutes * overtime_rate_cents_per_minute


# --------------------------------------------------------------------------
# calculations.ad_invoice_total
# --------------------------------------------------------------------------

def volume_discount_bp_of(ad_subtotal_cents):
    if ad_subtotal_cents >= 500000:
        return 1200
    if ad_subtotal_cents >= 250000:
        return 800
    if ad_subtotal_cents >= 100000:
        return 400
    return 0


def ad_invoice(ad_size, placement, insertion_count):
    """Returns (ad_subtotal_cents, volume_discount_bp, placement_fee_cents,
    invoice_total_cents) in the pinned evaluation order."""
    ad_subtotal_cents = AD_SIZE_RATE_CENTS[ad_size] * insertion_count
    volume_bp = volume_discount_bp_of(ad_subtotal_cents)
    discounted_subtotal = round_half_up(ad_subtotal_cents * (10000 - volume_bp), 10000)
    placement_fee_cents = round_half_up(discounted_subtotal * PLACEMENT_FEE_BP[placement], 10000)
    invoice_total_cents = discounted_subtotal + placement_fee_cents
    return ad_subtotal_cents, volume_bp, placement_fee_cents, invoice_total_cents


# --------------------------------------------------------------------------
# calculations.donor_level_derivation / patron_renewal_priority_score
# --------------------------------------------------------------------------

def donor_level_of(lifetime_donation_cents):
    for level, threshold in DONOR_THRESHOLDS:
        if lifetime_donation_cents >= threshold:
            return level
    return "NONE"


def renewal_priority_score(patron, current_year):
    since = patron.get("subscriber_since_year")
    seniority_years = 0 if since is None else max(0, current_year - since)
    return (patron["consecutive_renewal_years"] * 100
            + DONOR_POINTS[patron["donor_level"]]
            + seniority_years * 10)
