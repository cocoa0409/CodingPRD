"""Cascades, version bumps and conserved quantities (PRD 2.10, 3.5-3.9).

Every record a cascade rewrites is an independent mutation: its updated_at is
refreshed and its version increases by exactly 1.
"""
from calcs import (calc_accuracy_rollup, calc_cycle_financials,
                   calc_cycle_posture, plans_of, rollup_consensus)
from store import ordered, store, touch


def recompute_cycle(cycle, bump=True):
    """calc_cycle_financials followed immediately by calc_cycle_posture."""
    calc_cycle_financials(cycle)
    calc_cycle_posture(cycle)
    if bump:
        touch(cycle)


def allocations_of(plan_id):
    return ordered([a for a in store.allocations.values()
                    if a["supply_plan_id"] == plan_id])


def void_plan_allocations(plan):
    """Compensation, never deletion: the conservation identity survives exactly."""
    for a in allocations_of(plan["id"]):
        if a["allocation_status"] == "ALLOCATED":
            a["allocated_units"] = 0
            a["fill_rate_pct"] = 0.00
            a["allocation_pass"] = "NONE"
            a["allocation_status"] = "VOIDED"
            touch(a)
    plan["unallocated_units"] = plan["constrained_units"]


def stale_plan(plan):
    """PLANNED/RATIONED -> STALE with its allocation compensation."""
    was_rationed = plan["status"] == "RATIONED"
    plan["status"] = "STALE"
    plan["requires_replan"] = True
    if was_rationed:
        void_plan_allocations(plan)
    touch(plan)


def stale_plans_of_item(item_id, bump_cycles=True):
    """Every non-STALE supply plan of the item is invalidated."""
    affected = []
    for plan in ordered([p for p in store.supply_plans.values()
                         if p["item_id"] == item_id]):
        if plan["status"] in ("PLANNED", "RATIONED"):
            stale_plan(plan)
            if plan["cycle_id"] not in affected:
                affected.append(plan["cycle_id"])
    if bump_cycles:
        for cycle_id in affected:
            cycle = store.cycles.get(cycle_id)
            if cycle is not None:
                recompute_cycle(cycle, bump=True)
    return affected


def forecasts_of_item(item_id):
    return ordered([f for f in store.forecasts.values() if f["item_id"] == item_id])


def adjustments_on_forecasts(forecast_ids):
    return ordered([a for a in store.adjustments.values()
                    if a["demand_forecast_id"] in forecast_ids])


def promotions_of_item(item_id):
    return ordered([p for p in store.promotions.values() if p["item_id"] == item_id])


def void_adjustment(adjustment, recompute_line=True, bump_line=True):
    adjustment["applied_delta_units"] = 0
    adjustment["status"] = "VOIDED"
    touch(adjustment)
    if recompute_line:
        forecast = store.forecasts.get(adjustment["demand_forecast_id"])
        if forecast is not None:
            rollup_consensus(forecast)
            if bump_line:
                touch(forecast)


def truncate_forecast(forecast):
    forecast["status"] = "RUNOUT_TRUNCATED"
    forecast["consensus_units"] = 0
    touch(forecast)


def cancel_promotion_runout(promotion):
    """Promotion -> CANCELLED_RUNOUT plus the adjustment hop it causes."""
    was_approved = promotion["status"] == "APPROVED"
    promotion["status"] = "CANCELLED_RUNOUT"
    touch(promotion)
    if not was_approved:
        return
    for adjustment in ordered([a for a in store.adjustments.values()
                               if a["adjustment_type"] == "PROMOTION"
                               and a["promotion_id"] == promotion["id"]]):
        if adjustment["status"] in ("PROPOSED", "ENDORSED", "COMMITTED"):
            void_adjustment(adjustment)


def refresh_family_accuracy(family):
    """Rolling metrics over EVERY accuracy record of this family's items."""
    item_ids = set(i["id"] for i in store.items.values()
                   if i["family_id"] == family["id"])
    records = ordered([r for r in store.accuracy_records.values()
                       if r["item_id"] in item_ids])
    rollup = calc_accuracy_rollup(records)
    family["rolling_wmape_pct"] = rollup["wmape_pct"]
    family["rolling_bias_pct"] = rollup["bias_pct"]
    family["bias_flag"] = rollup["bias_flag"]
    family["accuracy_grade"] = rollup["accuracy_grade"]
    family["scored_record_count"] = rollup["record_count"]
    touch(family)


def open_adjustments_in_cycle(cycle_id):
    forecast_ids = set(f["id"] for f in store.forecasts.values()
                       if f["cycle_id"] == cycle_id)
    for a in store.adjustments.values():
        if (a["demand_forecast_id"] in forecast_ids
                and a["status"] in ("PROPOSED", "REVISION_REQUESTED")):
            return True
    return False


def open_adjustments_on_forecast(forecast_id):
    for a in store.adjustments.values():
        if (a["demand_forecast_id"] == forecast_id
                and a["status"] in ("PROPOSED", "REVISION_REQUESTED")):
            return True
    return False


def cycle_forecasts(cycle_id):
    return ordered([f for f in store.forecasts.values() if f["cycle_id"] == cycle_id])


def cycle_plans(cycle_id):
    return ordered(plans_of(cycle_id))


def cycle_scenarios(cycle_id):
    return ordered([s for s in store.scenarios.values() if s["cycle_id"] == cycle_id])
