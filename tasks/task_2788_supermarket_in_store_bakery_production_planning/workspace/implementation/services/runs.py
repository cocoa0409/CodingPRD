"""Production-run lifecycle: creation, cancellation, the completion cascade and
the waste/void shelf reversal (PRD 3.4, 3.5, 3.6)."""

from response import mark_new, touch
from store import db, new_entity
from services import purchasing
from services.calc import (
    final_labor_minutes,
    planned_labor_minutes,
    run_ingredient_cost_cents,
    run_timings,
    unit_cost_basis_cents,
)
from services.rollups import (
    derive_state_on_hand,
    has_open_order_for,
    recompute_bake_day,
    recompute_labels,
    set_state,
)
from util import q2


def create_run(day, product, oven, deck_index, rack_count, proof_start, bake_start, origin):
    bake_end, ready, expires = run_timings(product, proof_start, bake_start)
    row = new_entity(
        bake_day_id=day["id"],
        product_id=product["id"],
        oven_id=oven["id"] if oven is not None else None,
        deck_index=deck_index,
        origin=origin,
        rack_count=int(rack_count),
        planned_units=int(rack_count) * int(product["units_per_rack"]),
        proof_start_utc=proof_start,
        bake_start_utc=bake_start,
        bake_end_utc=bake_end,
        ready_utc=ready,
        expires_utc=expires,
        execution_status="SCHEDULED",
        disposition_status="PENDING",
        cancelled_reason=None,
        actual_units=None,
        actual_labor_minutes=None,
        planned_labor_minutes=planned_labor_minutes(product, rack_count),
        final_labor_minutes=None,
        ingredient_cost_cents=run_ingredient_cost_cents(product, rack_count),
        unit_cost_basis_cents=None,
        on_shelf_units=None,
        wasted_units_total=0,
        markdown_unit_price_cents=None,
        executed_by_user_id=None,
        shared_equipment_label_tags=[],
    )
    db.runs[row["id"]] = row
    mark_new(row)
    if row["oven_id"]:
        recompute_labels(row["oven_id"], day["id"])
    return row


def cancel_run(run, reason):
    run["execution_status"] = "CANCELLED"
    run["cancelled_reason"] = reason
    touch(run)
    if run.get("oven_id"):
        recompute_labels(run["oven_id"], run["bake_day_id"])
    return run


def complete_run(run, product, day, actual_units, actual_labor, caller):
    """PRD 3.5 -- the four-hop completion cascade."""
    run["actual_units"] = int(actual_units)
    run["actual_labor_minutes"] = q2(actual_labor) if actual_labor is not None else None
    run["executed_by_user_id"] = caller.user_id
    run["final_labor_minutes"] = final_labor_minutes(run, product, actual_labor)
    run["ingredient_cost_cents"] = int(run["ingredient_cost_cents"])
    run["wasted_units_total"] = 0
    if int(actual_units) > 0:
        run["unit_cost_basis_cents"] = unit_cost_basis_cents(run["ingredient_cost_cents"], actual_units)
        run["on_shelf_units"] = int(actual_units)
        run["disposition_status"] = "ON_SHELF"
    else:
        run["unit_cost_basis_cents"] = 0
        run["on_shelf_units"] = 0
        run["disposition_status"] = "CLEARED"
    run["execution_status"] = "COMPLETED"
    touch(run)

    # hop 1 -- the owning day absorbs the run.
    recompute_bake_day(day)

    # hops 2 to 4 -- recipe consumption, replenishment, purchase commitment.
    department = db.departments.get(day["department_id"])
    consumed = []
    for line in product["recipe_lines"]:
        ingredient = db.ingredients.get(line["ingredient_id"])
        if ingredient is None:
            continue
        ingredient["on_hand_units"] = int(ingredient["on_hand_units"]) - int(run["rack_count"]) * int(
            line["units_per_rack"]
        )
        touch(ingredient)
        consumed.append(ingredient)

    if department is not None and consumed:
        eligible = []
        for ingredient in consumed:
            if int(ingredient["on_hand_units"]) > int(ingredient["reorder_point_units"]):
                continue
            if has_open_order_for(department["id"], ingredient["id"]):
                continue
            if ingredient["replenishment_state"] == "OK":
                set_state(ingredient, derive_state_on_hand(ingredient))
            eligible.append(ingredient)
        purchasing.create_auto_reorder(department, eligible)
    return run


def recompute_run_shelf(run):
    """Re-derive wasted_units_total, on_shelf_units and the disposition from the
    run's ACTIVE waste records (PRD 3.6)."""
    wasted = 0
    for record in db.waste_records.values():
        if record["production_run_id"] != run["id"]:
            continue
        if record["record_status"] == "ACTIVE":
            wasted += int(record["units"])
    actual = int(run["actual_units"] or 0)
    on_shelf = actual - wasted
    if on_shelf < 0:
        on_shelf = 0
    changed = False
    if run["wasted_units_total"] != wasted:
        run["wasted_units_total"] = wasted
        changed = True
    if run["on_shelf_units"] != on_shelf:
        run["on_shelf_units"] = on_shelf
        changed = True
    if on_shelf == 0 and run["disposition_status"] in ("ON_SHELF", "MARKED_DOWN"):
        run["disposition_status"] = "CLEARED"
        changed = True
    elif on_shelf > 0 and run["disposition_status"] == "CLEARED":
        run["disposition_status"] = (
            "MARKED_DOWN" if run["markdown_unit_price_cents"] is not None else "ON_SHELF"
        )
        changed = True
    if changed:
        touch(run)
    return run


def attest_waste(run, reason, units, attested_by_user_id):
    """Mint an ACTIVE waste record against a completed run and cascade it into
    the run's shelf figures and the day's shrink rollups (PRD 3.6)."""
    basis = int(run["unit_cost_basis_cents"] or 0)
    record = new_entity(
        production_run_id=run["id"],
        bake_day_id=run["bake_day_id"],
        disposition_reason=reason,
        units=int(units),
        unit_cost_basis_cents=basis,
        waste_cost_cents=basis * int(units),
        record_status="ACTIVE",
        attested_by_user_id=attested_by_user_id,
        voided_by_user_id=None,
        void_reason=None,
    )
    db.waste_records[record["id"]] = record
    mark_new(record)
    recompute_run_shelf(run)
    day = db.bake_days.get(run["bake_day_id"])
    if day is not None:
        recompute_bake_day(day)
    return record
