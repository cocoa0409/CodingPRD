"""Calculation rules (SCAFFOLD §1.3, PRD §2.6, §2.9, §3.4, §3.6-§3.8, §3.10).

Rounding discipline (PRD §2.6): monetary aggregation sums integer cents exactly;
round-half-up is applied only at the pinned points — per-category subtotals
before summing (profit computation), per tier before summing (partner share),
and per batch (waste charge). All money math uses Decimal; never float.
"""

from decimal import Decimal, ROUND_HALF_UP

import db
from services import domain

_EXPENSE_CATEGORIES = ("COST_OF_GOODS", "LABOR", "CORPORATE_MARKETING_FEE", "MEAT_WASTE_CHARGE")
_REVENUE_CATEGORIES = ("REVENUE", "ADJUSTMENT")

CENT = Decimal("1")
WEIGHT_Q = Decimal("0.001")
SCORE_Q = Decimal("0.01")


def _round_cents(d):
    """Round a Decimal to integer cents, half-up."""
    return int(d.quantize(CENT, rounding=ROUND_HALF_UP))


def period_line_items(period_id):
    return [li for li in db.line_items.values() if li["period_id"] == period_id]


def period_batches(period_id):
    return [b for b in db.batches.values() if b["profit_period_id"] == period_id]


def consolidated_waste_charge_cents(period_id):
    """Sum of waste_charge_cents over batches in AUDITED_CONFORMING / VARIANCE_CONFIRMED.

    Waived batches contribute nothing (charge zeroed and status filtered out).
    """
    total = 0
    for b in period_batches(period_id):
        if b["status"] in domain.BATCH_WASTE_STATUSES:
            total += int(b.get("waste_charge_cents") or 0)
    return total


def restaurant_profit(period, variant):
    """PRD §2.9 / SCAFFOLD restaurant_profit_computation.

    variant "provisional": items in {PROVISIONAL, FINALIZED}, reads amount_cents.
    variant "final": FINALIZED items only, reads actual_amount_cents.
    Per-category subtotals are rounded to integer cents FIRST, then summed.
    """
    if variant == "provisional":
        statuses = ("PROVISIONAL", "FINALIZED")
        amount_key = "amount_cents"
    else:
        statuses = ("FINALIZED",)
        amount_key = "actual_amount_cents"

    # Per-category subtotals over partner-basis INCLUDED items.
    by_category = {}
    for li in period_line_items(period["id"]):
        if li["entry_status"] not in statuses:
            continue
        if li["partner_basis"] != "INCLUDED":
            continue  # CORPORATE_ADMIN_FEE is the excluded corporate charge
        by_category.setdefault(li["category"], Decimal(0))
        by_category[li["category"]] += Decimal(li[amount_key])

    revenue_total = 0
    expense_total = 0
    for category, subtotal in by_category.items():
        rounded = _round_cents(subtotal)  # round per category BEFORE summing
        if category in _REVENUE_CATEGORIES:
            revenue_total += rounded
        elif category in _EXPENSE_CATEGORIES:
            expense_total += rounded

    return revenue_total - expense_total - consolidated_waste_charge_cents(period["id"])


def partner_share(final_distributable_profit_cents):
    """PRD §3.6 / SCAFFOLD partner_share_tiering: marginal tiers, each tier rounded
    half-up to integer cents BEFORE summing; sum-then-round is forbidden."""
    p = int(final_distributable_profit_cents)
    if p <= 0:
        return 0
    tier1_base = min(p, domain.TIER1_CAP)
    tier2_base = max(0, min(p, domain.TIER2_CAP) - domain.TIER1_CAP)
    tier3_base = max(0, p - domain.TIER2_CAP)
    t1 = _round_cents(Decimal(tier1_base) * Decimal(domain.TIER1_RATE_PCT) / Decimal(100))
    t2 = _round_cents(Decimal(tier2_base) * Decimal(domain.TIER2_RATE_PCT) / Decimal(100))
    t3 = _round_cents(Decimal(tier3_base) * Decimal(domain.TIER3_RATE_PCT) / Decimal(100))
    return t1 + t2 + t3


def market_override(period, restaurant):
    """PRD §3.8 / SCAFFOLD market_partner_override. Returns integer cents (>= 0)."""
    group_id = restaurant.get("market_group_id")
    if group_id is None:
        return 0
    period_end = period["period_end_date"]
    candidate = None
    for a in db.agreements.values():
        if a["status"] != "ACTIVE":
            continue
        if a["market_group_id"] != group_id:
            continue
        # Closed interval, inclusive at both ends, must cover period_end_date.
        if a["coverage_start_date"] <= period_end <= a["coverage_end_date"]:
            candidate = a
            break
    if candidate is None:
        return 0

    p = int(period["final_distributable_profit_cents"])
    pct = Decimal(str(candidate["override_pct"])) / Decimal(100)
    if candidate["basis"] == "NET_GROUP_BASIS":
        group_count = sum(
            1
            for r in db.restaurants.values()
            if r.get("market_group_id") == group_id and r["status"] == "ACTIVE"
        )
        if group_count <= 0:
            return 0
        attributable = Decimal(p) / Decimal(group_count)
        return max(0, _round_cents(pct * attributable))
    # PER_RESTAURANT_POSITIVE
    return _round_cents(pct * Decimal(max(0, p)))


def meat_waste_charge(batch, standard, actual_yield_lbs):
    """PRD §3.7 / SCAFFOLD meat_waste_charge.

    Returns (actual_waste_lbs, excess_waste_lbs, waste_charge_cents, conforming).
    Weights are Decimal at 3dp; charge is per-batch round-half-up to integer cents.
    """
    weight = Decimal(str(batch["sub_primal_weight_lbs"])).quantize(WEIGHT_Q)
    actual_yield = Decimal(str(actual_yield_lbs)).quantize(WEIGHT_Q)
    expected_yield = weight * Decimal(str(standard["expected_yield_pct"])) / Decimal(100)
    expected_waste = weight - expected_yield
    allowed_waste = expected_waste * (Decimal(1) + Decimal(str(standard["waste_tolerance_pct"])) / Decimal(100))
    actual_waste = weight - actual_yield
    excess = actual_waste - allowed_waste
    # PRD §3.6: "per-category subtotals in the profit computation are rounded
    # to integer cents **before** the subtotals are summed" — waste charge is
    # rounded per batch (§3.7), at this point of computation.
    if excess <= 0:
        excess = Decimal(0)
        charge = 0
        conforming = True
    else:
        charge = _round_cents(excess * Decimal(standard["standard_cost_per_lb_cents"]))
        conforming = False
    return (
        float(actual_waste.quantize(WEIGHT_Q)),
        float(excess.quantize(WEIGHT_Q)),
        charge,
        conforming,
    )


def capital_return_depreciation(contract):
    """PRD §3.4 / SCAFFOLD capital_return_depreciation: straight-line depreciated buy-in.

    Half-open term interval [term_start_date, term_end_date): the day count is
    measured in integer days, so the return is
    round_half_up(buy_in_required_cents * (T - E) / T) — dividing after the
    multiplication keeps the numerator exact for integer day counts.
    """
    from datetime import date as _date

    term_start = _date.fromisoformat(contract["term_start_date"])
    term_end = _date.fromisoformat(contract["term_end_date"])
    departure = _date.fromisoformat(contract["departure_date"])
    T = (term_end - term_start).days
    E = (departure - term_start).days
    E = max(0, min(E, T))
    if T <= 0:
        return 0
    numerator = Decimal(contract["buy_in_required_cents"]) * Decimal(T - E)
    return _round_cents(numerator / Decimal(T))


def accrued_share(contract):
    """Sum of partner_share_cents over the contract restaurant's FINALIZED/LOCKED
    periods with partner_share_paid == false and period_end_date <= departure_date."""
    total = 0
    for p in db.periods.values():
        if p["restaurant_id"] != contract["restaurant_id"]:
            continue
        if p["status"] not in ("FINALIZED", "LOCKED"):
            continue
        if p.get("partner_share_paid"):
            continue
        if contract.get("departure_date") is None:
            continue
        if p["period_end_date"] > contract["departure_date"]:
            continue
        total += int(p.get("partner_share_cents") or 0)
    return total


def swept_periods(contract):
    """The periods whose accrued share a buyout order sweeps (same filter as accrual)."""
    out = []
    for p in db.periods.values():
        if p["restaurant_id"] != contract["restaurant_id"]:
            continue
        if p["status"] not in ("FINALIZED", "LOCKED"):
            continue
        if p.get("partner_share_paid"):
            continue
        if contract.get("departure_date") is None:
            continue
        if p["period_end_date"] > contract["departure_date"]:
            continue
        out.append(p)
    return out


def award_eligibility_score(period):
    """PRD §3.10 / SCAFFOLD award_eligibility_score. Returns float at 2dp (half-up)."""
    revenue = Decimal(0)
    for li in period_line_items(period["id"]):
        if li["entry_status"] == "FINALIZED" and li["category"] == "REVENUE":
            revenue += Decimal(li["actual_amount_cents"])

    sales_component = Decimal(50) * min(
        Decimal(1), revenue / Decimal(domain.SALES_TARGET_CENTS)
    )
    profit = Decimal(max(0, int(period.get("final_distributable_profit_cents") or 0)))
    margin = profit / max(Decimal(1), revenue)
    profit_margin_component = Decimal(30) * min(
        Decimal(1), margin / Decimal(str(domain.MARGIN_TARGET))
    )
    total_waste = Decimal(consolidated_waste_charge_cents(period["id"]))
    waste_ratio = min(Decimal(1), total_waste / Decimal(domain.WASTE_ALLOWANCE_CENTS))
    waste_component = Decimal(20) * (Decimal(1) - waste_ratio)

    score = sales_component + profit_margin_component + waste_component
    return float(score.quantize(SCORE_Q, rounding=ROUND_HALF_UP))
