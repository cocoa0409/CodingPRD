"""Calculation rules (PRD 2.9 and sections 3.2, 3.3, 3.5, 3.7, 3.8, 3.9).

All arithmetic runs over exact rationals (fractions.Fraction) so that no binary
float error can perturb a half-up rounding boundary. Money is integer cents.
"""
from decimal import Decimal
from fractions import Fraction

# --- rounding -------------------------------------------------------------
def rhu(value, places=0):
    """Round half up to `places` decimals, exactly (Fraction in, Fraction out)."""
    if not isinstance(value, Fraction):
        value = Fraction(value)
    scale = Fraction(10) ** places
    x = value * scale
    floored_half_up = (2 * x.numerator + x.denominator) // (2 * x.denominator)
    return Fraction(floored_half_up) / scale


def to_dec(value, places=2):
    if not isinstance(value, Fraction):
        value = Fraction(value)
    d = Decimal(value.numerator) / Decimal(value.denominator)
    return d.quantize(Decimal(1).scaleb(-places))


def to_cents(value):
    r = rhu(value, 0)
    return int(r)


def clamp(value, low, high):
    return max(Fraction(low), min(Fraction(high), value))


# --- tag_lot_issuance_fee (PRD 3.3) --------------------------------------
BASE_FEE_CENTS = 25000
PER_TAG_CENTS = 42
PROBATION_SURCHARGE_PCT = Fraction(4, 100)


def issuance_fee(quantity, probation):
    """Pinned order: subtotal -> volume discount off the PRE-surcharge subtotal
    -> discounted total -> probation surcharge off the DISCOUNTED total."""
    subtotal = BASE_FEE_CENTS + PER_TAG_CENTS * quantity
    if subtotal < 50000:
        pct = Fraction(0)
    elif subtotal < 150000:
        pct = Fraction(5, 100)
    elif subtotal < 400000:
        pct = Fraction(12, 100)
    else:
        pct = Fraction(18, 100)
    discount = to_cents(Fraction(subtotal) * pct)
    discounted = subtotal - discount
    surcharge = to_cents(Fraction(discounted) * PROBATION_SURCHARGE_PCT) if probation else 0
    return discounted + surcharge, to_dec(pct, 2), surcharge


# --- supplier_conformance_score (PRD 3.2) --------------------------------
DEFECT_WEIGHT = Fraction(12)
RETENTION_WEIGHT = Fraction(20)


def conformance(defect_report_count, issued_tag_count, retired_tag_count,
                retired_returned_count):
    """Returns (conformance_score Decimal(2dp), probation bool, issuance_cap int)."""
    denom = max(Fraction(1), Fraction(issued_tag_count, 1000))
    defects_per_thousand = Fraction(defect_report_count) / denom
    if retired_tag_count == 0:
        retention = Fraction(1)
    else:
        retention = rhu(Fraction(retired_returned_count, retired_tag_count), 4)
    raw = (Fraction(100)
           - DEFECT_WEIGHT * defects_per_thousand
           - RETENTION_WEIGHT * (Fraction(1) - retention))
    score = rhu(clamp(raw, 0, 100), 2)
    probation = score < Fraction(85)
    if score >= 95:
        cap = 10000
    elif score >= 85:
        cap = 5000
    elif score >= 70:
        cap = 2000
    else:
        cap = 0
    return to_dec(score, 2), probation, cap


# --- movement_reporting_timeliness (PRD 3.5) -----------------------------
ON_TIME_MAX_HOURS = Fraction(72)


def reporting_lag(hours_fraction):
    lag = rhu(hours_fraction, 2)
    return to_dec(lag, 2), lag <= ON_TIME_MAX_HOURS


def on_time_pct(numerator, denominator):
    if denominator == 0:
        return Decimal("100.00")
    return to_dec(rhu(Fraction(100) * Fraction(numerator, denominator), 2), 2)


# --- reconciliation_variance (PRD 3.8) -----------------------------------
def variance(physical_count, book_count):
    variance_count = physical_count - book_count
    pct = rhu(Fraction(100) * Fraction(abs(variance_count), max(1, book_count)), 2)
    return variance_count, to_dec(pct, 2)


# --- trace_completeness_score / trace_goal_evaluation (PRD 3.7) ----------
W_RESPONDED = Fraction(40)
W_RESOLVED = Fraction(35)
W_REACH = Fraction(25)
STALE_PREMISES_PENALTY = Fraction(10)
DISPUTE_PENALTY_EACH = Fraction(5)
DISPUTE_PENALTY_CAP = Fraction(15)


def completeness(hit_count, responded_count, resolved_count, hops_unreachable,
                 hops_total, stale_premises, disputed_hops):
    if hit_count == 0:
        return Decimal("100.00")
    responded_ratio = min(Fraction(1), Fraction(responded_count, hit_count))
    resolved_ratio = min(Fraction(1), Fraction(resolved_count, hit_count))
    reach_ratio = Fraction(1) - min(Fraction(1), Fraction(hops_unreachable, max(1, hops_total)))
    raw = (W_RESPONDED * responded_ratio + W_RESOLVED * resolved_ratio
           + W_REACH * reach_ratio)
    penalty = (STALE_PREMISES_PENALTY * (1 if stale_premises else 0)
               + min(DISPUTE_PENALTY_CAP, DISPUTE_PENALTY_EACH * disputed_hops))
    return to_dec(rhu(clamp(raw - penalty, 0, 100), 2), 2)


TRACE_GOAL_HOURS = Fraction(48)
MIN_COMPLETENESS = Fraction(80)


def trace_goal(elapsed_hours_dec, completeness_dec):
    return (Fraction(elapsed_hours_dec) <= TRACE_GOAL_HOURS
            and Fraction(completeness_dec) >= MIN_COMPLETENESS)


# --- incentive_award_amount (PRD 3.9) ------------------------------------
BASE_RATE_CENTS_PER_HEAD = Fraction(137)


def tier_for_head_count(head_count):
    if head_count <= 0:
        return "TIER_0", Fraction(0)
    if head_count <= 99:
        return "TIER_1", Fraction(1)
    if head_count <= 499:
        return "TIER_2", Fraction(115, 100)
    return "TIER_3", Fraction(130, 100)


def compliance_multiplier(on_time_pct_value):
    p = Fraction(on_time_pct_value)
    if p >= 95:
        return Fraction(125, 100)
    if p >= 80:
        return Fraction(1)
    if p >= 50:
        return Fraction(60, 100)
    return Fraction(0)


def award_line_cents(animal_count, tier_factor, compliance):
    """Rounded to whole cents per line - never deferred to the sum."""
    return to_cents(BASE_RATE_CENTS_PER_HEAD * Fraction(animal_count)
                    * tier_factor * compliance)
