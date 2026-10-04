"""Every calculation rule from SCAFFOLD 1.3 / PRD 3, implemented in Decimal.

Never use float for money. Round-half-up is half away from zero.
"""

from decimal import Decimal

from common import dec, round_half_up_int, quantize


# --------------------------------------------------------------------------
# combined_credit_underwriting (SCAFFOLD 1.3)
# --------------------------------------------------------------------------
TIER_LADDER = (
    (750, "A", Decimal("2.75")),
    (700, "B", Decimal("3.75")),
    (650, "C", Decimal("5.50")),
    (600, "D", Decimal("7.25")),
)


def tier_of(score):
    for threshold, tier, margin in TIER_LADDER:
        if score >= threshold:
            return tier, margin
    return "DECLINED", None


def combined_credit_score(borrower, cosigner, variant):
    """variant is 'provisional' or 'final'.

    An eligible cosigner is one referenced by the application whose
    underwriting_status is ELIGIBLE. A cosigner in INVITED, INELIGIBLE or
    RELEASED contributes nothing.
    """
    b_score = int(borrower.get("credit_score") or 0)
    has_cosigner = (
        cosigner is not None and cosigner.get("underwriting_status") == "ELIGIBLE"
    )
    c_score = int(cosigner.get("credit_score") or 0) if cosigner else 0

    if variant == "provisional":
        return max(b_score, c_score) if has_cosigner else b_score

    # final variant
    if has_cosigner:
        return round_half_up_int(Decimal("0.55") * c_score + Decimal("0.45") * b_score)
    return b_score - 25


def price_application(borrower, cosigner, variant):
    """Returns (combined_credit_score, tier, margin_rate_pct)."""
    score = combined_credit_score(borrower, cosigner, variant)
    tier, margin = tier_of(score)
    return score, tier, margin


# --------------------------------------------------------------------------
# in_school_interest_accrual_dual (SCAFFOLD 1.3)
# --------------------------------------------------------------------------
def accrued_per_period(principal_cents, effective_rate_pct, window_months):
    """Round each month independently and sum (booked ledger / live read)."""
    p = dec(principal_cents)
    monthly_rate = dec(effective_rate_pct) / Decimal(100) / Decimal(12)
    per_month = p * monthly_rate
    total = 0
    for _ in range(int(window_months)):
        total += round_half_up_int(per_month)
    return total


def accrued_consolidated(principal_cents, effective_rate_pct, window_months):
    """Round exactly once over the whole window (projection only)."""
    p = dec(principal_cents)
    annual_rate = dec(effective_rate_pct) / Decimal(100)
    value = p * annual_rate * dec(window_months) / Decimal(12)
    return round_half_up_int(value)


# --------------------------------------------------------------------------
# capitalized_interest_cap (SCAFFOLD 1.3)
# --------------------------------------------------------------------------
def max_allowed_capitalization(disbursed_amount_cents, cap_pct):
    """capitalized_interest_cap_pct * disbursed_amount_cents, half up to cent."""
    product = dec(cap_pct) * dec(disbursed_amount_cents)
    return round_half_up_int(quantize(product, 2))


def capitalized_interest(uncapped_cents, disbursed_amount_cents, cap_pct):
    """min(uncapped, cap) with an INCLUSIVE boundary: when uncapped == cap the
    whole unpaid amount is capitalized (SCAFFOLD 1.3 exact-boundary rule)."""
    cap = max_allowed_capitalization(disbursed_amount_cents, cap_pct)
    return min(uncapped_cents, cap), cap


# --------------------------------------------------------------------------
# monthly_payment_amortization (SCAFFOLD 1.3)
# --------------------------------------------------------------------------
def monthly_payment_cents(principal_snapshot_cents, rate_snapshot_pct, term_months):
    p = dec(principal_snapshot_cents)
    r = dec(rate_snapshot_pct) / Decimal(100) / Decimal(12)
    n = int(term_months)
    if n <= 0:
        return 0
    if r == 0:
        return round_half_up_int(p / Decimal(n))
    denominator = Decimal(1) - (Decimal(1) + r) ** (-n)
    quotient = p * r / denominator
    quotient = quantize(quotient, 2)
    return round_half_up_int(quotient)


# --------------------------------------------------------------------------
# cosigner_release_eligibility_score (SCAFFOLD 1.3)
# --------------------------------------------------------------------------
def release_score(independent_credit_score, independent_dti_ratio,
                  run_at_submission, required_min_payments):
    credit_component = min(300, max(0, int(independent_credit_score) - 550))
    dti_raw = round_half_up_int(
        (Decimal("0.60") - dec(independent_dti_ratio)) * Decimal(1000)
    )
    dti_component = min(250, max(0, dti_raw))
    if required_min_payments and required_min_payments > 0:
        run_raw = round_half_up_int(
            Decimal(200) * dec(run_at_submission) / dec(required_min_payments)
        )
    else:
        run_raw = 200
    run_component = min(200, max(0, run_raw))
    return credit_component + dti_component + run_component


# --------------------------------------------------------------------------
# autodebit_waiver_benefit (SCAFFOLD 1.3)
# --------------------------------------------------------------------------
def reduction_applies(autodebit_enrolled, lifetime_on_time_payment_count,
                      min_payments_before_reduction):
    return bool(autodebit_enrolled) and int(lifetime_on_time_payment_count or 0) >= int(
        min_payments_before_reduction
    )


def effective_rate_pct(margin_rate_pct, autodebit_enrolled, lifetime_on_time_payment_count,
                       min_payments_before_reduction, reduction_pct):
    """effective_rate_pct is margin minus the reduction actually in force,
    expressed to four decimal places, rounded half up."""
    margin = dec(margin_rate_pct or 0)
    if reduction_applies(autodebit_enrolled, lifetime_on_time_payment_count,
                         min_payments_before_reduction):
        margin = margin - dec(reduction_pct)
    return float(quantize(margin, 4))


def max_autodebit_waiver_benefit_cents(current_balance_cents, reduction_pct,
                                       in_school_months_with_immediate_accrual):
    value = (
        dec(current_balance_cents)
        * (dec(reduction_pct) / Decimal(100))
        * (dec(in_school_months_with_immediate_accrual) / Decimal(12))
    )
    return round_half_up_int(value)