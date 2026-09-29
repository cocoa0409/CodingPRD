"""Production plan generation: the supersede pass, the ordered walk and the
earliest-feasible-slot search (PRD 3.3)."""

from errors import ApiError
from response import touch
from store import by_seq, db
from services.calc import (
    DAYPART_OFFSET_HOURS,
    DAYPART_RANK,
    affordable_racks,
    deck_collides,
    effective_demand,
    per_rack_labor,
    required_racks,
)
from services.rollups import ACTIVE_EXECUTION, recompute_bake_day, runs_of_day
from services.runs import cancel_run, create_run
from util import add_hours, add_minutes, dec, q2

GRID_MINUTES = 5


def oven_accepts(oven, product):
    """Both halves of the allergen rule (PRD 2.8)."""
    if product["allergen_free_claim"] and oven["allergen_mode"] != "NUT_FREE_DEDICATED":
        return False
    if oven["allergen_mode"] != "SHARED":
        for tag in product["allergen_tags"]:
            if tag in ("PEANUT", "TREE_NUT"):
                return False
    return True


def candidate_ovens(department_id, product):
    ovens = [
        oven
        for oven in db.ovens.values()
        if oven["department_id"] == department_id
        and oven["oven_status"] == "AVAILABLE"
        and oven_accepts(oven, product)
    ]
    return sorted(ovens, key=lambda row: (row["name"], row["_seq"]))


def earliest_feasible_slot(day, product, daypart):
    """(oven, deck_index, bake_start) for the earliest feasible pairing, else None."""
    shift_start = day["oven_shift_start_utc"]
    shift_end = day["oven_shift_end_utc"]
    target = add_hours(shift_start, DAYPART_OFFSET_HOURS[daypart])
    tail_minutes = int(product["bake_minutes"]) + int(product["cool_minutes"])
    best = None
    for oven in candidate_ovens(day["department_id"], product):
        for deck in range(int(oven["deck_count"])):
            step = 0
            while True:
                instant = add_minutes(target, GRID_MINUTES * step)
                if add_minutes(instant, tail_minutes) > shift_end:
                    break
                proof_start = add_minutes(instant, -int(product["proof_minutes"]))
                if proof_start >= shift_start:
                    end = add_minutes(instant, int(product["bake_minutes"]))
                    if not deck_collides(oven, deck, instant, end):
                        candidate = (instant, oven["name"], deck, oven)
                        if best is None or (candidate[0], candidate[1], candidate[2]) < (
                            best[0],
                            best[1],
                            best[2],
                        ):
                            best = candidate
                        break
                step += 1
    if best is None:
        return None
    return best[3], best[2], best[0]


def sorted_forecast_lines(day):
    decorated = []
    for index, line in enumerate(day["forecast_lines"]):
        product = db.products.get(line["product_id"])
        sku = product["sku"] if product else ""
        decorated.append((DAYPART_RANK[line["daypart"]], sku, index, line))
    decorated.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
    return [entry[3] for entry in decorated]


def generate_plan(day):
    """Regenerate the day's plan in place; raises ERR_EMPTY_PRODUCTION_PLAN when
    the walk creates nothing."""
    # -- supersede pass -----------------------------------------------------
    for run in runs_of_day(day["id"]):
        if run["origin"] == "PLAN_GENERATED" and run["execution_status"] == "SCHEDULED":
            cancel_run(run, "PLAN_SUPERSEDED")

    # -- accumulators -------------------------------------------------------
    committed = q2(0)
    for run in runs_of_day(day["id"]):
        if run["execution_status"] in ACTIVE_EXECUTION:
            committed += q2(run["planned_labor_minutes"])
    unmet = 0
    day["plan_unmet_unit_count"] = 0

    budget = dec(day["labor_budget_minutes"])
    created = []

    # -- the ordered walk ---------------------------------------------------
    for line in sorted_forecast_lines(day):
        product = db.products.get(line["product_id"])
        if product is None:
            continue
        demand = effective_demand(line["forecasted_units"], day["day_of_week"])
        if demand == 0:
            continue
        required = required_racks(demand, product["units_per_rack"])
        remaining = budget - dec(committed)
        if per_rack_labor(product) == 0:
            affordable = required
        else:
            affordable = affordable_racks(product, remaining, required)

        oven = None
        deck = None
        proof_start = None
        bake_start = None
        if product["production_method"] == "THAW_AND_SERVE":
            equipment_cap = required
        else:
            slot = earliest_feasible_slot(day, product, line["daypart"])
            if slot is None:
                unmet += demand
                continue
            oven, deck, bake_start = slot
            equipment_cap = int(oven["rack_capacity_per_deck"])
            if int(product["proof_minutes"]) > 0:
                proof_start = add_minutes(bake_start, -int(product["proof_minutes"]))

        granted = min(required, affordable, equipment_cap)
        if granted <= 0:
            unmet += demand
            continue

        run = create_run(day, product, oven, deck, granted, proof_start, bake_start, "PLAN_GENERATED")
        created.append(run)
        committed = q2(dec(committed) + dec(run["planned_labor_minutes"]))
        shortfall = demand - granted * int(product["units_per_rack"])
        if shortfall > 0:
            unmet += shortfall

    if not created:
        raise ApiError("ERR_EMPTY_PRODUCTION_PLAN")

    day["plan_unmet_unit_count"] = unmet
    day["plan_posture"] = "PLANNED"
    recompute_bake_day(day)
    touch(day)
    return day
