"""State transitions, cascade propagation and the two sweep runs."""

from datetime import timedelta
from decimal import Decimal

import calc
from calc import ZERO, q2, q4
from db import clock_dt, clock_date, db, touch


# --------------------------------------------------------------------------
# PRD 2.10 penalty ledger
# --------------------------------------------------------------------------

def rescore_customer(customer):
    """Recompute compliance_penalty_points and advance the commercial axis."""
    points = calc.customer_penalty_points(customer)
    changed = False
    if customer["compliance_penalty_points"] != points:
        customer["compliance_penalty_points"] = points
        changed = True
    if customer["trading_status"] == "ACTIVE" and points >= calc.CREDIT_HOLD_POINTS:
        customer["trading_status"] = "CREDIT_HOLD"
        customer["credit_hold_reason"] = "AUTO: compliance penalty points %d" % points
        changed = True
    if customer["trading_status"] == "CREDIT_HOLD" and points >= calc.SUSPENSION_POINTS:
        customer["trading_status"] = "SUSPENDED"
        changed = True
    if changed:
        touch(customer)
    return changed


# --------------------------------------------------------------------------
# PRD 2.9 / 3.7 spend axis and the overspend consequence
# --------------------------------------------------------------------------

def apply_spend_cascade(promo):
    """Hops 2-4: the first time a promotion reaches OVERSPENT the owning
    allocation counts the event, moves to RESTRICTED posture and re-scores its
    customer.  Recovery never decrements the counter."""
    ratio, status = calc.promotion_spend(promo)
    if status != "OVERSPENT" or promo.get("_ever_overspent"):
        return
    promo["_ever_overspent"] = True
    alloc = db.allocations.get(promo["allocation_id"])
    if alloc is None:
        return
    alloc["overspend_event_count"] += 1
    touch(alloc)
    customer = db.customers.get(alloc["customer_id"])
    if customer is not None:
        rescore_customer(customer)


# --------------------------------------------------------------------------
# PRD 3.10 post-event analysis
# --------------------------------------------------------------------------

def consumption_facts(promo):
    return [row for row in db.facts.values()
            if row["customer_id"] == promo["customer_id"]
            and row["brand_id"] == promo["brand_id"]
            and row["fact_type"] == "CONSUMPTION"]


def recovered_total(promo):
    total = ZERO
    for ded in calc.deductions_of_promotion(promo["id"]):
        for dis in calc.disputes_of_deduction(ded["id"]):
            if dis["status"] == "RECOVERED" and dis["recovered_amount"] is not None:
                total += dis["recovered_amount"]
    return q2(total)


def compute_analysis_values(promo, baseline_method):
    brand = db.brands.get(promo["brand_id"])
    unit_margin = brand["unit_margin"] if brand is not None else ZERO
    window_start = promo["window_start"]
    window_end = promo["window_end"]
    weeks = (window_end - window_start).days // 7

    trailing_from = window_start - timedelta(days=7 * calc.TRAILING_BASELINE_WEEKS)
    post_to = window_end + timedelta(days=7 * calc.POST_PERIOD_WEEKS)

    trailing_facts = []
    promo_facts = []
    post_facts = []
    for row in consumption_facts(promo):
        period = row["period_start"]
        if trailing_from <= period < window_start:
            trailing_facts.append(row)
        elif window_start <= period < window_end:
            promo_facts.append(row)
        elif window_end <= period < post_to:
            post_facts.append(row)

    promo_units = sum(row["units"] for row in promo_facts)
    net_spend = q2(calc.promotion_ledger(promo)["recognized_spend_amount"] - recovered_total(promo))

    if not promo_facts:
        return {
            "baseline_method": baseline_method,
            "baseline_weekly_units": ZERO,
            "promo_consumption_units": promo_units,
            "baseline_units": ZERO,
            "lift_units": ZERO,
            "post_period_units": 0,
            "cannibalization_units": ZERO,
            "net_incremental_units": ZERO,
            "incremental_gross_profit": ZERO,
            "net_spend": net_spend,
            "roi": None,
            "data_status": "INSUFFICIENT_DATA",
        }

    if baseline_method == "TRAILING":
        trailing_units = sum(row["units"] for row in trailing_facts)
        baseline_weekly = q2(Decimal(trailing_units) / Decimal(calc.TRAILING_BASELINE_WEEKS))
    else:
        baseline_weekly = q2(Decimal(brand["baseline_units_per_week"] if brand else 0))

    baseline_units = q2(baseline_weekly * Decimal(weeks))
    lift_units = q2(Decimal(promo_units) - baseline_units)
    post_period_units = sum(row["units"] for row in post_facts)
    expected_post = q2(baseline_weekly * Decimal(calc.POST_PERIOD_WEEKS))
    shortfall = expected_post - Decimal(post_period_units)
    cannibalization = q2(shortfall) if shortfall > 0 else ZERO
    net_incremental = q2(lift_units - cannibalization)
    gross_profit = q2(net_incremental * unit_margin)
    roi = None if net_spend <= ZERO else q4(gross_profit / net_spend)
    return {
        "baseline_method": baseline_method,
        "baseline_weekly_units": baseline_weekly,
        "promo_consumption_units": promo_units,
        "baseline_units": baseline_units,
        "lift_units": lift_units,
        "post_period_units": post_period_units,
        "cannibalization_units": cannibalization,
        "net_incremental_units": net_incremental,
        "incremental_gross_profit": gross_profit,
        "net_spend": net_spend,
        "roi": roi,
        "data_status": "COMPLETE",
    }


def recompute_analysis(promo):
    """Cascaded in-place recompute; the pinned baseline_method is reused."""
    analysis = calc.analysis_of_promotion(promo["id"])
    if analysis is None:
        return None
    values = compute_analysis_values(promo, analysis["baseline_method"])
    analysis.update(values)
    analysis["computed_at"] = clock_dt()
    touch(analysis)
    return analysis


# --------------------------------------------------------------------------
# PRD 3.7 weekly accrual assembly
# --------------------------------------------------------------------------

def accrual_context(promo, period_start):
    method = promo["accrual_method"]
    if method == "SHIPMENT":
        return method, period_start + timedelta(days=calc.SHIP_LEAD_DAYS), "SHIPMENT"
    return method, period_start, "CONSUMPTION"


def accrual_components(promo, period_start):
    method, effective, fact_type = accrual_context(promo, period_start)
    fact_units = 0
    for row in db.facts.values():
        if (row["customer_id"] == promo["customer_id"]
                and row["brand_id"] == promo["brand_id"]
                and row["fact_type"] == fact_type
                and row["period_start"] == period_start):
            fact_units += row["units"]
    lines = []
    total = ZERO
    for tactic in calc.live_tactics(promo["id"]):
        if not (tactic["window_start"] <= effective < tactic["window_end"]):
            continue
        if tactic["tactic_type"] == "TPR":
            amount = q2(Decimal(fact_units) * tactic["rate_per_case"])
        else:
            amount = q2(tactic["fixed_fee"] / Decimal(calc.tactic_week_count(tactic)))
        lines.append({"tactic_id": tactic["id"], "amount": amount})
        total += amount
    return method, effective, fact_units, lines, q2(total)


# --------------------------------------------------------------------------
# PRD 3.7 activation sweep
# --------------------------------------------------------------------------

def run_activation():
    today = clock_date()
    activated = []
    ended = []
    tactics_activated = []
    tactics_completed = []
    for promo in sorted(db.promotions.values(), key=lambda r: r["_seq"]):
        if promo["lifecycle_status"] == "APPROVED" and promo["window_start"] <= today:
            promo["lifecycle_status"] = "LIVE"
            touch(promo)
            activated.append(promo["id"])
        if promo["lifecycle_status"] != "LIVE":
            continue
        lines = calc.tactics_of_promotion(promo["id"])
        for tactic in lines:
            if (tactic["status"] == "PLANNED"
                    and tactic["window_start"] <= today < tactic["window_end"]):
                tactic["status"] = "ACTIVE"
                touch(tactic)
                tactics_activated.append(tactic["id"])
        for tactic in lines:
            if tactic["status"] == "ACTIVE" and tactic["window_end"] <= today:
                tactic["status"] = "COMPLETED"
                touch(tactic)
                tactics_completed.append(tactic["id"])
        if promo["window_end"] <= today:
            promo["lifecycle_status"] = "ENDED"
            touch(promo)
            ended.append(promo["id"])
            for tactic in lines:
                if tactic["status"] == "PLANNED" and tactic["window_end"] <= today:
                    tactic["status"] = "COMPLETED"
                    touch(tactic)
                    tactics_completed.append(tactic["id"])
    return {
        "promotions_activated": activated,
        "promotions_ended": ended,
        "tactics_activated": tactics_activated,
        "tactics_completed": tactics_completed,
    }


# --------------------------------------------------------------------------
# PRD 3.9 aging sweep
# --------------------------------------------------------------------------

def run_aging():
    candidates = [d for d in db.disputes.values()
                  if d["status"] in ("OPEN", "AWAITING_RETAILER")]
    candidates.sort(key=lambda d: (d["opened_at"], d["created_at"], d["_seq"]))
    escalated = []
    penalized = []
    for dispute in candidates:
        if calc.dispute_aging_days(dispute) < calc.AGING_ESCALATION_DAYS:
            continue
        dispute["status"] = "ESCALATED"
        touch(dispute)
        escalated.append(dispute["id"])
        deduction = db.deductions.get(dispute["deduction_id"])
        if deduction is None:
            continue
        customer = db.customers.get(deduction["customer_id"])
        if customer is None:
            continue
        if rescore_customer(customer) and customer["id"] not in penalized:
            penalized.append(customer["id"])
    return {
        "disputes_scanned": len(candidates),
        "disputes_escalated": escalated,
        "customers_penalized": penalized,
    }
