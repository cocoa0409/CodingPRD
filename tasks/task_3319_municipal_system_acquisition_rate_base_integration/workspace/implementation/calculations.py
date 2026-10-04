"""Calculation rules from SCAFFOLD.yaml Table 3, implemented exactly as
specified. All monetary math is integer cents with round-half-up.
"""
from decimal import Decimal, ROUND_HALF_UP

import db
from util import (
    PLANNING_CONTINGENCY, FILING_CONTINGENCY, PREMIUM_CAP_RATE,
    COUNCIL_PASS_PCT, REFERENDUM_TRIGGER_PCT, REFERENDUM_PASS_PCT,
    PHASE_IN_CAP_PCT,
)


def _round_half_up_int(value):
    """Round a Decimal to an integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_estimates(assessment):
    """capital_need_estimate. Items in PLANNED/SCHEDULED/EXECUTED count;
    SPLIT and CANCELLED are excluded. Filing variant rounds each midpoint
    per item first, then sums."""
    items = [i for i in db.capital_items_of_assessment(assessment["id"])
             if i["status"] in ("PLANNED", "SCHEDULED", "EXECUTED")]
    sum_low = sum(i["cost_low_cents"] for i in items)
    sum_mid = sum(i["midpoint_estimate_cents"] for i in items)
    planning = _round_half_up_int(Decimal(sum_low) * (Decimal(1) + Decimal(str(PLANNING_CONTINGENCY))))
    filing = _round_half_up_int(Decimal(sum_mid) * (Decimal(1) + Decimal(str(FILING_CONTINGENCY))))
    assessment["planning_estimate_cents"] = planning
    assessment["filing_estimate_cents"] = filing


def rate_base_admission(application, target):
    """rate_base_admission, computed on APPROVED."""
    purchase = application["purchase_price_cents"]
    selected_value = target["selected_value_cents"]
    premium_cap = _round_half_up_int(Decimal(selected_value) * Decimal(str(PREMIUM_CAP_RATE)))
    as_paid_admission = min(purchase, selected_value + premium_cap)
    if application["rate_base_method"] == "DEPRECIATED_ORIGINAL_COST":
        base_admission = min(purchase, application["original_cost_less_depreciation_cents"])
    else:
        base_admission = as_paid_admission
    ceiling = target["filing_estimate_cents"] + selected_value + premium_cap
    admitted = min(base_admission, ceiling)
    return admitted, purchase - admitted


def compute_yes_share_pct(yes_votes, no_votes):
    """round_half_up(yes / (yes + no) * 100, 2 dp). Returns a float with 2dp."""
    total = yes_votes + no_votes
    share = (Decimal(yes_votes) / Decimal(total) * Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(share)


def vote_outcome(kind, yes_share_pct):
    """Returns (passed, referendum_available, hard_fail)."""
    if kind == "COUNCIL_VOTE":
        passed = yes_share_pct >= COUNCIL_PASS_PCT
        referendum_available = (REFERENDUM_TRIGGER_PCT <= yes_share_pct < COUNCIL_PASS_PCT)
        hard_fail = yes_share_pct < REFERENDUM_TRIGGER_PCT
        return passed, referendum_available, hard_fail
    # REFERENDUM: strict majority — exactly 50.00 FAILS, 50.01 passes.
    passed = yes_share_pct > REFERENDUM_PASS_PCT
    return passed, False, not passed


def deposit_settlement(account):
    """Pinned evaluation order: offset, then new AR, then refund."""
    offset = min(account["deposit_cents"], account["ar_balance_cents"])
    new_ar = account["ar_balance_cents"] - offset
    refund = account["deposit_cents"] - offset
    return offset, refund, new_ar


def severance_calc(employee):
    """Inclusive tiers: >=10 -> 8; >=5 -> 4; >=1 -> 2; else 1."""
    years = employee["years_of_service"]
    if years >= 10:
        weeks = 8
    elif years >= 5:
        weeks = 4
    elif years >= 1:
        weeks = 2
    else:
        weeks = 1
    return weeks, weeks * employee["weekly_salary_cents"]


def phase_in_schedule(tariff):
    """cap_per_year = round_half_up(old * 5/100); delta<=0 -> 0 years; else ceil."""
    old = tariff["representative_old_bill_cents"]
    new = tariff["consolidated_monthly_bill_cents"]
    cap = _round_half_up_int(Decimal(old) * Decimal(PHASE_IN_CAP_PCT) / Decimal(100))
    delta = new - old
    if delta <= 0:
        return 0
    years, remainder = divmod(delta, cap)
    return years + (1 if remainder else 0)
