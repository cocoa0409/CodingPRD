"""recognition_snapshot_calculation (SCAFFOLD 1.3 / PRD 3.9).

PROJECTED variant: recognition_pct of a forward-looking lifetime projection.
ACTUAL variant: settled billings deflated by the fixed target margin.
"""
from decimal import Decimal

from calc import (
    LLP_RESET_CYCLES,
    MARGIN_FLOOR_PCT,
    SEVERITY_COST_FACTOR,
    TARGET_MARGIN_PCT,
    WORKSCOPE_BASE_COST_USD,
    effective_rate,
)
from money import round2, round4
from storage import DB, now
from timeutil import clock_period, period_index


def _ceil_div(n, d):
    return -((-n) // d)


def build_snapshot_fields(agreement):
    """Compute the seven snapshot figures at the current logical clock."""
    clock = now()
    current_period = clock_period(clock)
    end_period = (agreement["end_date"].year, agreement["end_date"].month)
    remaining_term_months = max(0, period_index(end_period) - period_index(current_period))

    engines = [e for e in DB["engines"].values() if e["agreement_id"] == agreement["id"]]

    projected_monthly_revenue = Decimal(0)
    for engine in engines:
        rate_now = effective_rate(agreement, engine, current_period)
        projected_monthly_revenue += (engine["assumed_annual_hours"] / 12) * rate_now

    lifetime_revenue = round2(
        agreement["billed_to_date_usd"] + remaining_term_months * projected_monthly_revenue)

    # cost_to_date: APPROVED workscope totals of COMPLETED visits of enrolled
    # engines, plus lease_cost of RETURNED leases on those visits.
    cost_to_date = Decimal(0)
    for engine in engines:
        for visit in DB["visits"].values():
            if visit["engine_id"] != engine["id"] or visit["status"] != "COMPLETED":
                continue
            for w in DB["workscopes"].values():
                if w["shop_visit_id"] == visit["id"] and w["status"] == "APPROVED":
                    cost_to_date += w["total_cost_usd"]
            for lease in DB["leases"].values():
                if lease["shop_visit_id"] == visit["id"] and lease["status"] == "RETURNED":
                    cost_to_date += lease["lease_cost_usd"]
    cost_to_date = round2(cost_to_date)

    lifetime_cost = cost_to_date
    for engine in engines:
        forecast_visits = _ceil_div(
            remaining_term_months * engine["assumed_cycles_per_month"], LLP_RESET_CYCLES)
        per_visit = round2(WORKSCOPE_BASE_COST_USD * SEVERITY_COST_FACTOR[engine["base_severity_tier"]])
        lifetime_cost += forecast_visits * per_visit
    lifetime_cost = round2(lifetime_cost)

    if lifetime_cost == 0:
        recognition_pct = Decimal("0.0000")
    else:
        recognition_pct = round4(min(Decimal(1), cost_to_date / lifetime_cost))

    recognized_projected = round2(recognition_pct * lifetime_revenue)

    settled_billing = sum(
        (s["final_total_usd"] for s in DB["statements"].values()
         if s["agreement_id"] == agreement["id"] and s["status"] == "SETTLED"),
        Decimal(0),
    )
    recognized_actual = round2(settled_billing * (Decimal(1) - TARGET_MARGIN_PCT))

    if lifetime_revenue == 0:
        projected_margin = Decimal(0)
    else:
        projected_margin = (lifetime_revenue - lifetime_cost) / lifetime_revenue
    if projected_margin < MARGIN_FLOOR_PCT:
        onerous_loss = round2(lifetime_cost - lifetime_revenue)
    else:
        onerous_loss = Decimal("0.00")

    return {
        "agreement_id": agreement["id"],
        "lifetime_revenue_projection_usd": lifetime_revenue,
        "lifetime_cost_projection_usd": lifetime_cost,
        "cost_to_date_usd": cost_to_date,
        "recognition_pct": recognition_pct,
        "recognized_revenue_projected_usd": recognized_projected,
        "recognized_revenue_actual_usd": recognized_actual,
        "onerous_loss_accrual_usd": onerous_loss,
    }
