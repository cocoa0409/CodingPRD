"""The thirteen pinned calculations (PRD 2.6, 3.4-3.9).

All money is integer cents and every fractional cent is rounded HALF UP at
exactly the step the calculation names. Percentages are round-half-up to two
decimal places, except `expense_rebate_pct` which carries one.
"""

from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import clockcal

HUNDRED = Decimal(100)

# ---- pinned constants ----------------------------------------------------
PLAN_MATCH_CAP_PCT = Decimal("6.0")
SAFE_HARBOR_BASIC_TIER_1_PCT = Decimal("3")
SAFE_HARBOR_BASIC_TIER_2_LIMIT_PCT = Decimal("5")
SAFE_HARBOR_ENHANCED_PCT = Decimal("4")

DAY_COUNT_BASIS = Decimal(365)
IRS_6621_ANNUAL_RATE_PCT = {
    (2025, 1): Decimal("7.0"),
    (2025, 2): Decimal("7.0"),
    (2025, 3): Decimal("7.0"),
    (2025, 4): Decimal("7.0"),
    (2026, 1): Decimal("7.0"),
    (2026, 2): Decimal("8.0"),
    (2026, 3): Decimal("9.0"),
    (2026, 4): Decimal("9.0"),
    (2027, 1): Decimal("9.0"),
    (2027, 2): Decimal("9.0"),
    (2027, 3): Decimal("9.0"),
    (2027, 4): Decimal("9.0"),
}

EXCISE_TAX_RATE_PCT = Decimal("15")
EXCISE_TAX_DE_MINIMIS_CENTS = 10000

COVERAGE_RATIO_PASS_PCT = Decimal("70.00")
ADP_TIER_1_PCT = Decimal("2.00")
ADP_TIER_1_MULTIPLIER = Decimal("2.00")
ADP_TIER_2_PCT = Decimal("8.00")
ADP_TIER_2_ADDEND = Decimal("2.00")
ADP_TIER_3_MULTIPLIER = Decimal("1.25")

REBATE_TIER_1_FLOOR_CENTS = 1000000
REBATE_TIER_1_PCT = Decimal("2.0")
REBATE_TIER_2_FLOOR_CENTS = 5000000
REBATE_TIER_2_PCT = Decimal("5.0")
REBATE_TIER_0_PCT = Decimal("0.0")

EXIT_ADMIN_FEE_CENTS_PER_PARTICIPANT = 1250
EXIT_FLAT_FEE_CENTS = 250000

BOND_PCT_OF_ASSETS = Decimal("0.10")
BOND_FLOOR_CENTS = 100000
BOND_CEILING_CENTS = 100000000

MONTHS_AFTER_PLAN_YEAR_END = 7
PLAN_AUDIT_PARTICIPANT_THRESHOLD = 1000
SMALL_PLAN_PARTICIPANT_THRESHOLD = 100
SAFE_HARBOR_BUSINESS_DAYS = 7
GENERAL_RULE_BUSINESS_DAY_OF_MONTH = 15
BLACKOUT_BUFFER_DAYS = 5

WITHHOLDING_GRACE_DAYS = 31


# --------------------------------------------------------------------------
# Rounding primitives
# --------------------------------------------------------------------------


def cents(value):
    """Round a fractional cent HALF UP to a whole cent."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pct2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pct1(value):
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def pct_of(amount, percent):
    """`percent` percent of `amount`, kept exact."""
    return Decimal(amount) * Decimal(percent) / HUNDRED


# --------------------------------------------------------------------------
# 1. business_days_elapsed / late_by_business_days  (PRD 3.5)
# --------------------------------------------------------------------------


def business_days_elapsed(withholding_date, deposit_date):
    return clockcal.business_days_between(withholding_date, deposit_date)


def late_by_business_days(deposit_due_date, deposit_date):
    return clockcal.business_days_between(deposit_due_date, deposit_date)


# --------------------------------------------------------------------------
# 2. deposit_due_date  (PRD 3.4)
# --------------------------------------------------------------------------


def deposit_due_date(deposit_rule, withholding_date):
    if deposit_rule == "SMALL_PLAN_7_BUSINESS_DAY":
        return clockcal.nth_business_day_after(
            withholding_date, SAFE_HARBOR_BUSINESS_DAYS
        )
    year, month = clockcal.add_months(
        withholding_date.year, withholding_date.month, 1
    )
    return clockcal.nth_business_day_of_month(
        year, month, GENERAL_RULE_BUSINESS_DAY_OF_MONTH
    )


# --------------------------------------------------------------------------
# 3. employer_match_amount  (PRD 3.4)
#
# Each tier is rounded half up to whole cents first, the rounded tiers are then
# summed, and only then is the plan-wide cap applied.
# --------------------------------------------------------------------------


def expected_match_cents(election, compensation_cents, deferral_cents):
    comp = Decimal(compensation_cents)
    deferrals = Decimal(deferral_cents)
    code = election["match_formula_code"]

    if code == "SAFE_HARBOR_BASIC":
        first_limit = pct_of(comp, SAFE_HARBOR_BASIC_TIER_1_PCT)
        tier_1 = cents(min(deferrals, first_limit))
        second_limit = pct_of(comp, SAFE_HARBOR_BASIC_TIER_2_LIMIT_PCT)
        excess = min(deferrals, second_limit) - first_limit
        if excess < 0:
            excess = Decimal(0)
        tier_2 = cents(excess / Decimal(2))
        raw = tier_1 + tier_2
    elif code == "SAFE_HARBOR_ENHANCED":
        raw = cents(min(deferrals, pct_of(comp, SAFE_HARBOR_ENHANCED_PCT)))
    elif code == "DISCRETIONARY_TIERED":
        limit_1 = pct_of(comp, election["match_tier_1_limit_pct"])
        tier_1 = cents(
            pct_of(min(deferrals, limit_1), election["match_tier_1_pct"])
        )
        limit_2 = pct_of(comp, election["match_tier_2_limit_pct"])
        excess = min(deferrals, limit_2) - limit_1
        if excess < 0:
            excess = Decimal(0)
        tier_2 = cents(pct_of(excess, election["match_tier_2_pct"]))
        raw = tier_1 + tier_2
    else:  # NONE
        raw = 0

    cap = cents(pct_of(comp, PLAN_MATCH_CAP_PCT))
    return min(raw, cap)


# --------------------------------------------------------------------------
# 4. lost_earnings  (PRD 3.5)
# --------------------------------------------------------------------------


def _quarter_rate(d):
    key = (d.year, clockcal.quarter_of(d))
    if key in IRS_6621_ANNUAL_RATE_PCT:
        return IRS_6621_ANNUAL_RATE_PCT[key]
    # Outside the published window, hold the nearest published rate.
    if d.year < 2025:
        return IRS_6621_ANNUAL_RATE_PCT[(2025, 1)]
    return IRS_6621_ANNUAL_RATE_PCT[(2027, 4)]


def _interest(principal_cents, annual_rate_pct, days):
    return Decimal(principal_cents) * (annual_rate_pct / HUNDRED) * Decimal(
        days
    ) / DAY_COUNT_BASIS


def lost_earnings_irs_6621(principal_cents, deposit_due_date_, deposit_date):
    """A single rate -- that of the quarter containing the deposit date -- over
    the plain calendar-day difference between the deposit date and the due date."""
    days = (deposit_date - deposit_due_date_).days
    if days <= 0:
        return 0
    rate = _quarter_rate(deposit_date)
    return cents(_interest(principal_cents, rate, days))


def _quarter_segments(start, end):
    """Split [start, end] into calendar-quarter segments, chronologically."""
    segments = []
    cur = start
    while cur <= end:
        quarter = clockcal.quarter_of(cur)
        last_month = quarter * 3
        q_end = clockcal.last_day_of_month(cur.year, last_month)
        seg_end = min(q_end, end)
        segments.append((cur, seg_end))
        cur = seg_end + clockcal.timedelta(days=1)
    return segments


def lost_earnings_vfcp(principal_cents, deposit_due_date_, recovery_date):
    """Segment by calendar quarter, round each segment, then sum."""
    start = deposit_due_date_ + clockcal.timedelta(days=1)
    if recovery_date < start:
        return 0
    total = 0
    for seg_start, seg_end in _quarter_segments(start, recovery_date):
        days = (seg_end - seg_start).days + 1
        rate = _quarter_rate(seg_start)
        total += cents(_interest(principal_cents, rate, days))
    return total


def lost_earnings(method, principal_cents, deposit_due_date_, deposit_date,
                  recovery_date):
    if method == "IRS_6621_UNDERPAYMENT":
        return lost_earnings_irs_6621(
            principal_cents, deposit_due_date_, deposit_date
        )
    return lost_earnings_vfcp(principal_cents, deposit_due_date_, recovery_date)


# --------------------------------------------------------------------------
# 5. excise_tax_5330  (PRD 3.5)
# --------------------------------------------------------------------------


def restoration_cents(lost_earnings_cents, actual_investment_return_cents):
    return max(lost_earnings_cents, actual_investment_return_cents)


def excise_tax_cents(restoration):
    if restoration < EXCISE_TAX_DE_MINIMIS_CENTS:
        return 0
    return cents(pct_of(restoration, EXCISE_TAX_RATE_PCT))


# --------------------------------------------------------------------------
# 6. coverage_ratio_percentage  (PRD 3.6)
# --------------------------------------------------------------------------


def coverage_ratio(benefiting_hce, hce_population, benefiting_nhce,
                   nhce_population):
    if hce_population > 0:
        hce_pct = pct2(Decimal(benefiting_hce) * HUNDRED / Decimal(hce_population))
    else:
        hce_pct = pct2(0)
    if nhce_population > 0:
        nhce_pct = pct2(
            Decimal(benefiting_nhce) * HUNDRED / Decimal(nhce_population)
        )
    else:
        nhce_pct = pct2(0)
    if hce_pct == 0:
        # No highly compensated employee benefits: the coverage requirement is
        # not capable of being failed by the ratio, so it is met whenever any
        # non-highly compensated employee benefits.
        ratio = pct2(HUNDRED) if nhce_pct > 0 else pct2(0)
    else:
        ratio = pct2(nhce_pct * HUNDRED / hce_pct)
    return hce_pct, nhce_pct, ratio


# --------------------------------------------------------------------------
# 7. adp_acp_limit  (PRD 3.6)
# --------------------------------------------------------------------------


def weighted_average(pairs):
    """Headcount-weighted average, rounded half up to two decimals."""
    total_weight = sum(w for _, w in pairs)
    if total_weight == 0:
        return pct2(0)
    numerator = sum(Decimal(v) * Decimal(w) for v, w in pairs)
    return pct2(numerator / Decimal(total_weight))


def adp_limit(nhce_avg_pct):
    if nhce_avg_pct <= ADP_TIER_1_PCT:
        return pct2(nhce_avg_pct * ADP_TIER_1_MULTIPLIER)
    if nhce_avg_pct <= ADP_TIER_2_PCT:
        return pct2(nhce_avg_pct + ADP_TIER_2_ADDEND)
    return pct2(nhce_avg_pct * ADP_TIER_3_MULTIPLIER)


# --------------------------------------------------------------------------
# 8. net_plan_expense  (PRD 3.9) -- runs FIRST
# --------------------------------------------------------------------------


def expense_rebate_pct(gross_direct_fees_cents):
    if gross_direct_fees_cents >= REBATE_TIER_2_FLOOR_CENTS:
        return pct1(REBATE_TIER_2_PCT)
    if gross_direct_fees_cents >= REBATE_TIER_1_FLOOR_CENTS:
        return pct1(REBATE_TIER_1_PCT)
    return pct1(REBATE_TIER_0_PCT)


def net_plan_expense(participant_count, direct_fee_sum, revenue_sharing_pool_cents):
    gross = participant_count * direct_fee_sum
    rebate_pct = expense_rebate_pct(gross)
    rebate = cents(pct_of(gross, rebate_pct))
    rebated = gross - rebate
    offset = min(revenue_sharing_pool_cents, rebated)
    return {
        "gross_direct_fees_cents": gross,
        "expense_rebate_pct": rebate_pct,
        "revenue_sharing_offset_cents": offset,
        "net_plan_expense_cents": rebated - offset,
    }


# --------------------------------------------------------------------------
# 9. revenue_sharing_allocation  (PRD 3.9) -- runs SECOND, largest remainder
# --------------------------------------------------------------------------


def revenue_sharing_allocation(eligible, allocation_method, pool_cents):
    """`eligible` is the eligible employer rows in created_at ascending order."""
    if allocation_method == "PRO_RATA_ASSETS":
        bases = [e["account_balance_cents"] for e in eligible]
    else:
        bases = [e["participant_count"] for e in eligible]
    total_basis = sum(bases)

    if total_basis == 0 or not eligible:
        return {
            "allocation_lines": [],
            "total_revenue_sharing_allocated_cents": 0,
            "residual_cents_distributed": 0,
            "eligible_employer_count": len(eligible),
            "credits": {},
        }

    entries = []
    for index, (employer, basis) in enumerate(zip(eligible, bases)):
        raw = Fraction(pool_cents * basis, total_basis)
        floor = raw.numerator // raw.denominator
        remainder = raw - floor
        share_pct = pct2(Decimal(basis) * HUNDRED / Decimal(total_basis))
        entries.append(
            {
                "employer": employer,
                "order": index,
                "basis_amount": basis,
                "basis_share_pct": share_pct,
                "floor": floor,
                "remainder": remainder,
                "residual_awarded": 0,
            }
        )

    residual = pool_cents - sum(e["floor"] for e in entries)
    ranked = sorted(entries, key=lambda e: (-e["remainder"], e["order"]))
    for entry in ranked[:max(residual, 0)]:
        entry["residual_awarded"] = 1

    for entry in entries:
        entry["credit_cents"] = entry["floor"] + entry["residual_awarded"]

    ordered = sorted(entries, key=lambda e: (-e["credit_cents"], e["order"]))
    lines = [
        {
            "adopting_employer_id": e["employer"]["id"],
            "basis_amount": e["basis_amount"],
            "basis_share_pct": e["basis_share_pct"],
            "credit_cents": e["credit_cents"],
            "residual_awarded": e["residual_awarded"],
        }
        for e in ordered
    ]
    return {
        "allocation_lines": lines,
        "total_revenue_sharing_allocated_cents": sum(
            e["credit_cents"] for e in entries
        ),
        "residual_cents_distributed": residual,
        "eligible_employer_count": len(eligible),
        "credits": {e["employer"]["id"]: e["credit_cents"] for e in entries},
    }


# --------------------------------------------------------------------------
# 10. exit_settlement_waterfall  (PRD 3.8)
# --------------------------------------------------------------------------


def exit_waterfall(gross_balance_cents, transferred_participant_count, exit_type):
    admin = EXIT_ADMIN_FEE_CENTS_PER_PARTICIPANT * transferred_participant_count
    flat = 0 if exit_type == "PLAN_TERMINATION_DISTRIBUTION" else EXIT_FLAT_FEE_CENTS
    taken_admin = min(admin, gross_balance_cents)
    remainder = gross_balance_cents - taken_admin
    taken_flat = min(flat, remainder)
    applied = taken_admin + taken_flat
    return {
        "transferred_participant_count": transferred_participant_count,
        "gross_account_balance_cents": gross_balance_cents,
        "admin_recovery_cents": admin,
        "flat_exit_fee_cents": flat,
        "deductions_applied_cents": applied,
        "unrecovered_deduction_cents": admin + flat - applied,
        "transfer_amount_cents": gross_balance_cents - applied,
        "settled_amount_cents": gross_balance_cents,
    }


# --------------------------------------------------------------------------
# 11. fidelity_bond_minimum  (PRD 3.7)
# --------------------------------------------------------------------------


def fidelity_bond_minimum(total_assets_cents):
    raw = cents(Decimal(total_assets_cents) * BOND_PCT_OF_ASSETS)
    if raw < BOND_FLOOR_CENTS:
        return BOND_FLOOR_CENTS
    if raw > BOND_CEILING_CENTS:
        return BOND_CEILING_CENTS
    return raw


# --------------------------------------------------------------------------
# 12. filing_deadline_date  (PRD 3.7)
# --------------------------------------------------------------------------


def filing_deadline_date(plan_year_end_date):
    year, month = clockcal.add_months(
        plan_year_end_date.year, plan_year_end_date.month,
        MONTHS_AFTER_PLAN_YEAR_END,
    )
    return clockcal.roll_forward_to_business_day(
        clockcal.last_day_of_month(year, month)
    )
