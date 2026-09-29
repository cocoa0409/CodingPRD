"""Income-shares guideline worksheet (PRD 3.3), five ordered steps."""
from decimal import Decimal

import util

IMPUTED_INCOME_CENTS = 182000
SELF_SUPPORT_RESERVE_CENTS = 113200
MINIMUM_ORDER_CENTS = 5000
MULTI_FAMILY_CREDIT_PCT = Decimal("0.10")

# (band ceiling or None for unbounded, {children -> rate})
BANDS = [
    (400000, {1: Decimal("0.20"), 2: Decimal("0.28"), 3: Decimal("0.33")}),
    (800000, {1: Decimal("0.17"), 2: Decimal("0.25"), 3: Decimal("0.30")}),
    (None, {1: Decimal("0.14"), 2: Decimal("0.21"), 3: Decimal("0.25")}),
]


def qualifies_for_imputation(ncp):
    """Absent income, or income that is not attributable to a source."""
    return (ncp.get("monthly_gross_income_cents") is None
            or ncp.get("income_verification_source") == "NONE")


def band_rate(combined_income_cents, child_count):
    key = 3 if child_count >= 3 else child_count
    for ceiling, rates in BANDS:
        if ceiling is None or combined_income_cents <= ceiling:
            return rates[key]
    return BANDS[-1][1][key]


def compute(cp, ncp, child_count):
    """Return every guideline field the worksheet writes."""
    # Step 1 — incomes, with imputation for the obligor when it applies.
    cp_income = cp.get("monthly_gross_income_cents") or 0
    if qualifies_for_imputation(ncp):
        ncp_income = IMPUTED_INCOME_CENTS
        imputation_applied = True
    else:
        ncp_income = ncp.get("monthly_gross_income_cents") or 0
        imputation_applied = False

    # Step 2 — combined income, band selection, basic obligation.
    combined = cp_income + ncp_income
    rate = band_rate(combined, child_count)
    basic = util.mul_round_half_up(combined, rate)

    # Step 3 — the obligor's proportional share.
    ratio = util.ratio_4dp(ncp_income, combined) if combined else Decimal("0.0000")
    ncp_share = util.mul_round_half_up(basic, ratio)

    # Step 4 — multi-family credit, applied BEFORE the self-support reserve.
    if ncp.get("supports_second_family"):
        credit = util.mul_round_half_up(ncp_share, MULTI_FAMILY_CREDIT_PCT)
    else:
        credit = 0
    after_credit = ncp_share - credit

    # Step 5 — self-support reserve, then the statutory minimum order.
    available = ncp_income - SELF_SUPPORT_RESERVE_CENTS
    if available <= 0:
        monthly = MINIMUM_ORDER_CENTS
    else:
        monthly = min(after_credit, available)

    return {
        "guideline_cp_income_cents": cp_income,
        "guideline_ncp_income_cents": ncp_income,
        "guideline_basic_obligation_cents": basic,
        "guideline_ncp_share_ratio": ratio,
        "multi_family_credit_cents": credit,
        "imputation_applied": imputation_applied,
        "guideline_monthly_cents": monthly,
    }
