"""Pure calculation rules (PRD 2.6 and section 3).  No store access here.

All money is integer cents; every fractional monetary expression is rounded
half up.  Decimal is used everywhere — never float arithmetic.
"""
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")

# --- constants ---------------------------------------------------------------
AUTH_BUFFER_MULT = Decimal("1.15")
SERVICE_FEE_CENTS = 399
WEIGHT_VARIANCE_PCT = Decimal("0.20")
MARKUP_PCT_MAX = Decimal("0.60")

BASE_PAY_CENTS = 700
UNIT_RATE_CENTS = 25
HEAVY_TIER_1_LB = Decimal("50.0")
HEAVY_TIER_1_CENTS = 300
HEAVY_TIER_2_LB = Decimal("80.0")
HEAVY_TIER_2_CENTS = 600
HEAVY_TIER_3_LB = Decimal("120.0")
HEAVY_TIER_3_CENTS = 900
MILEAGE_FREE_MI = Decimal("8.0")
MILEAGE_RATE_CENTS_PER_MI = Decimal("60")
MILEAGE_BONUS_CAP_CENTS = 1200
MULTI_STORE_BONUS_CENTS = 250

TIP_BAIT_PCT_NUMERATOR = 50
TIP_PROTECTION_CAP_CENTS = 1000
GUARANTEE_PER_UNIT_CENTS = 80

ROLLING_WINDOW_N = 5
RATING_WEIGHT = Decimal("0.70")
RELIABILITY_WEIGHT = Decimal("0.30")
ABANDONMENT_RELIABILITY_DIVISOR = Decimal("5")
DIAMOND_MIN_SCORE = Decimal("0.9200")
DIAMOND_MIN_COMPLETED = 3
PLATINUM_MIN_SCORE = Decimal("0.8000")
STANDARD_MIN_SCORE = Decimal("0.6000")
ABANDONMENT_SUSPENSION_THRESHOLD = 2
REINSTATEMENT_MIN_SCORE = Decimal("0.6000")

FLAT_INCONVENIENCE_CENTS = 500
ABANDON_CREDIT_CAP_CENTS = 2500

PARITY_DISCLOSURE_THRESHOLD_PCT = Decimal("0.10")

OFFER_TTL_MINUTES = 30
TIP_WINDOW_HOURS = 2
REPLACEMENT_TTL_MINUTES = 20
TIP_ADJUSTMENT_MAX_COUNT = 2
SHOPPER_TURNAROUND_BUFFER_MIN = 15

TIER_RANK = {"PROBATION": 0, "STANDARD": 1, "PLATINUM": 2, "DIAMOND": 3}
TIERS = ("PROBATION", "STANDARD", "PLATINUM", "DIAMOND")


# --- primitives -------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimals."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    return int(rhu(value, 0))


def one_dp(value):
    return rhu(value, 1)


def four_dp(value):
    return rhu(value, 4)


# --- catalog ----------------------------------------------------------------
def catalog_price_cents(in_store_price_cents, markup_pct):
    return cents(dec(in_store_price_cents) * (Decimal(1) + dec(markup_pct)))


# --- line money -------------------------------------------------------------
def est_line_cents(unit_price_cents, pricing_unit, requested_qty, requested_weight_lb):
    """Estimated money for one line (ESTIMATE variant, per-line rounding)."""
    if pricing_unit == "PER_LB":
        return cents(dec(unit_price_cents) * dec(requested_weight_lb))
    return int(unit_price_cents) * int(requested_qty)


def priced_line_cents(unit_price_cents, pricing_unit, qty, weight_lb):
    """Money for one line from an effective quantity / weight."""
    if pricing_unit == "PER_LB":
        return cents(dec(unit_price_cents) * dec(weight_lb))
    return int(unit_price_cents) * int(qty)


def weight_of(line):
    final_weight = dec(line["final_weight_lb"])
    if final_weight > 0:
        return final_weight
    return dec(line["requested_weight_lb"])


def qty_of(line):
    if line["status"] in ("PICKED", "REPLACED"):
        return int(line["picked_qty"])
    return int(line["requested_qty"])


def weight_variance_ok(final_weight_lb, requested_weight_lb):
    diff = abs(dec(final_weight_lb) - dec(requested_weight_lb))
    return diff <= dec(requested_weight_lb) * WEIGHT_VARIANCE_PCT


# --- shopper scoring --------------------------------------------------------
def mean_stars(stars_list):
    if not stars_list:
        return Decimal("0.0")
    total = sum(int(s) for s in stars_list)
    return four_dp(Decimal(total) / Decimal(len(stars_list)))


def tier_score(avg, has_ratings, abandonment_count):
    if has_ratings:
        rating_component = (dec(avg) - Decimal(1)) / Decimal(4)
    else:
        rating_component = ZERO
    reliability = Decimal(1) - (Decimal(int(abandonment_count)) / ABANDONMENT_RELIABILITY_DIVISOR)
    if reliability < 0:
        reliability = ZERO
    return four_dp(RATING_WEIGHT * rating_component + RELIABILITY_WEIGHT * reliability)


def tier_of(score, completed_batch_count):
    score = dec(score)
    if score >= DIAMOND_MIN_SCORE and int(completed_batch_count) >= DIAMOND_MIN_COMPLETED:
        return "DIAMOND"
    if score >= PLATINUM_MIN_SCORE:
        return "PLATINUM"
    if score >= STANDARD_MIN_SCORE:
        return "STANDARD"
    return "PROBATION"


# --- shopper pay ------------------------------------------------------------
def heavy_pay_cents(total_weight_lb):
    weight = dec(total_weight_lb)
    if weight >= HEAVY_TIER_3_LB:
        return HEAVY_TIER_3_CENTS
    if weight >= HEAVY_TIER_2_LB:
        return HEAVY_TIER_2_CENTS
    if weight >= HEAVY_TIER_1_LB:
        return HEAVY_TIER_1_CENTS
    return 0


def mileage_bonus_cents(total_distance_mi):
    excess = dec(total_distance_mi) - MILEAGE_FREE_MI
    if excess < 0:
        excess = ZERO
    raw = cents(excess * MILEAGE_RATE_CENTS_PER_MI)
    return min(MILEAGE_BONUS_CAP_CENTS, raw)


def work_pay(total_units, total_weight_lb, total_distance_mi, store_count):
    base = BASE_PAY_CENTS + UNIT_RATE_CENTS * int(total_units)
    heavy = heavy_pay_cents(total_weight_lb)
    mileage = mileage_bonus_cents(total_distance_mi)
    multi = MULTI_STORE_BONUS_CENTS * max(0, int(store_count) - 1)
    return {
        "base_pay_cents": base,
        "heavy_pay_cents": heavy,
        "mileage_bonus_cents": mileage,
        "multi_store_bonus_cents": multi,
        "batch_pay_cents": base + heavy + mileage + multi,
    }


def assemble_payout(batch_pay_cents, tip_pass_through_cents, tip_baseline_cents, total_units, variant):
    """Steps S1..S6 of the payout assembly, in the pinned order."""
    tip_cut = tip_baseline_cents - tip_pass_through_cents
    if tip_cut < 0:
        tip_cut = 0
    protection_eligible = tip_baseline_cents > 0 and (tip_cut * 100) >= (
        tip_baseline_cents * TIP_BAIT_PCT_NUMERATOR
    )
    if variant == "PROVISIONAL":
        tip_protection = 0
    elif protection_eligible:
        tip_protection = min(TIP_PROTECTION_CAP_CENTS, tip_cut)
    else:
        tip_protection = 0
    subtotal = batch_pay_cents + tip_pass_through_cents + tip_protection
    guarantee_floor = GUARANTEE_PER_UNIT_CENTS * int(total_units)
    top_up = guarantee_floor - subtotal
    if top_up < 0:
        top_up = 0
    return {
        "tip_pass_through_cents": tip_pass_through_cents,
        "tip_protection_cents": tip_protection,
        "guarantee_top_up_cents": top_up,
        "total_payout_cents": subtotal + top_up,
    }


# --- abandonment credit -----------------------------------------------------
def abandonment_credit_cents(estimated_subtotal_cents, total_lines, picked_lines):
    if picked_lines > 0 and (picked_lines * 2) >= total_lines:
        rate = Decimal("0.10")
    elif picked_lines > 0:
        rate = Decimal("0.05")
    else:
        rate = ZERO
    raw = FLAT_INCONVENIENCE_CENTS + cents(dec(estimated_subtotal_cents) * rate)
    return min(raw, ABANDON_CREDIT_CAP_CENTS)


# --- parity -----------------------------------------------------------------
def effective_markup_pct(markup_cents, in_store_subtotal_cents):
    if in_store_subtotal_cents == 0:
        return Decimal("0.0000")
    return four_dp(dec(markup_cents) / dec(in_store_subtotal_cents))


def parity_credit_cents(markup_cents, in_store_subtotal_cents, disclosure_required_flag):
    if disclosure_required_flag:
        return 0
    threshold = cents(dec(in_store_subtotal_cents) * PARITY_DISCLOSURE_THRESHOLD_PCT)
    return max(0, markup_cents - threshold)
