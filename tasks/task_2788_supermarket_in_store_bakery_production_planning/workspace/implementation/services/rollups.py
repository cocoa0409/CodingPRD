"""Derived-field recomputation: bake-day rollups, shrink ratios and the
markdown gate, shared-equipment labels, slot reservations, the department's
purchase commitment and ingredient replenishment states.

Every helper writes only when a value actually changed, and delegates the
version bump to response.touch() so a row never advances twice in one request
(PRD 2.4).
"""

from store import by_seq, db
from response import touch
from services.calc import ratio4
from util import q2

ACTIVE_EXECUTION = ("SCHEDULED", "PROOFING", "BAKING", "COMPLETED")


def runs_of_day(bake_day_id):
    return by_seq([row for row in db.runs.values() if row["bake_day_id"] == bake_day_id])


def waste_of_day(bake_day_id):
    return by_seq([row for row in db.waste_records.values() if row["bake_day_id"] == bake_day_id])


def orders_of_slot(slot_id):
    return by_seq([row for row in db.cake_orders.values() if row["pickup_slot_id"] == slot_id])


# ---------------------------------------------------------------------------
# bake day
# ---------------------------------------------------------------------------

def recompute_bake_day(day):
    """Recompute the nine rollups, both shrink ratios and the markdown gate."""
    runs = runs_of_day(day["id"])
    planned_labor = q2(0)
    planned_units = 0
    actual_labor = q2(0)
    produced_units = 0
    production_cost = 0
    for run in runs:
        if run["execution_status"] in ACTIVE_EXECUTION:
            planned_labor += q2(run["planned_labor_minutes"])
            planned_units += int(run["planned_units"])
        if run["execution_status"] == "COMPLETED":
            if run["final_labor_minutes"] is not None:
                actual_labor += q2(run["final_labor_minutes"])
            produced_units += int(run["actual_units"] or 0)
            production_cost += int(run["ingredient_cost_cents"] or 0)

    waste_units = 0
    shrink_cost = 0
    for record in waste_of_day(day["id"]):
        if record["record_status"] == "ACTIVE":
            waste_units += int(record["units"])
            shrink_cost += int(record["waste_cost_cents"])

    updates = {
        "planned_labor_minutes": q2(planned_labor),
        "planned_units_total": planned_units,
        "actual_labor_minutes": q2(actual_labor),
        "produced_units_total": produced_units,
        "production_cost_cents": production_cost,
        "waste_units_total": waste_units,
        "shrink_cost_cents": shrink_cost,
        "shrink_cost_basis_pct": ratio4(shrink_cost, production_cost),
        "shrink_unit_basis_pct": ratio4(waste_units, produced_units),
    }
    changed = False
    ratio_moved = day["shrink_cost_basis_pct"] != updates["shrink_cost_basis_pct"]
    for field, value in updates.items():
        if day[field] != value:
            day[field] = value
            changed = True

    # The markdown gate follows the cost-basis ratio only (PRD 2.7 / 3.6); the
    # value supplied when the day was opened stands until that ratio moves.
    department = db.departments.get(day["department_id"])
    if ratio_moved and department is not None:
        budget = department["shrink_budget_pct"]
        desired = "MANAGER_ONLY" if day["shrink_cost_basis_pct"] > budget else "AUTO"
        if day["markdown_authorization"] != desired:
            day["markdown_authorization"] = desired
            changed = True

    if changed:
        touch(day)
    return day


# ---------------------------------------------------------------------------
# shared-equipment labels (PRD 2.8)
# ---------------------------------------------------------------------------

def label_tags_for(oven_id, bake_day_id):
    tags = set()
    for run in db.runs.values():
        if run.get("oven_id") != oven_id or run["bake_day_id"] != bake_day_id:
            continue
        if run["execution_status"] == "CANCELLED":
            continue
        product = db.products.get(run["product_id"])
        if product is not None:
            tags.update(product["allergen_tags"])
    return sorted(tags)


def recompute_labels(oven_id, bake_day_id):
    """Relabel every non-cancelled run sharing this oven and bake day."""
    if not oven_id:
        return
    tags = label_tags_for(oven_id, bake_day_id)
    for run in by_seq(list(db.runs.values())):
        if run.get("oven_id") != oven_id or run["bake_day_id"] != bake_day_id:
            continue
        if run["execution_status"] == "CANCELLED":
            continue
        if run["shared_equipment_label_tags"] != tags:
            run["shared_equipment_label_tags"] = list(tags)
            touch(run)


# ---------------------------------------------------------------------------
# pickup slot reservation (PRD 3.7)
# ---------------------------------------------------------------------------

RESERVING_STATUSES = ("CONFIRMED", "IN_DECORATION", "READY")


def recompute_slot(slot):
    reserved = 0
    for order in orders_of_slot(slot["id"]):
        if order["order_status"] in RESERVING_STATUSES:
            reserved += int(order["decoration_units"])
    if slot["reserved_decoration_units"] != reserved:
        slot["reserved_decoration_units"] = reserved
        touch(slot)
    return slot


def reserved_excluding(slot, order_id):
    reserved = 0
    for order in orders_of_slot(slot["id"]):
        if order["id"] == order_id:
            continue
        if order["order_status"] in RESERVING_STATUSES:
            reserved += int(order["decoration_units"])
    return reserved


# ---------------------------------------------------------------------------
# department commitment (PRD 3.8)
# ---------------------------------------------------------------------------

COMMITTING_STATUSES = ("DRAFT", "SUBMITTED")


def recompute_commitment(department, force=False):
    committed = 0
    for order in db.ingredient_orders.values():
        if order["department_id"] != department["id"]:
            continue
        if order["order_status"] in COMMITTING_STATUSES:
            committed += int(order["order_total_cents"])
    changed = department["open_purchase_commitment_cents"] != committed
    if changed:
        department["open_purchase_commitment_cents"] = committed
    if changed or force:
        touch(department)
    return department


# ---------------------------------------------------------------------------
# ingredient replenishment (PRD 3.1, 3.5, 3.8)
# ---------------------------------------------------------------------------

def has_open_order_for(department_id, ingredient_id):
    for order in db.ingredient_orders.values():
        if order["department_id"] != department_id:
            continue
        if order["order_status"] not in COMMITTING_STATUSES:
            continue
        for line in order["lines"]:
            if line["ingredient_id"] == ingredient_id:
                return True
    return False


def derive_state_on_hand(ingredient):
    """OK at or above the reorder point, REORDER_DUE strictly below."""
    if int(ingredient["on_hand_units"]) >= int(ingredient["reorder_point_units"]):
        return "OK"
    return "REORDER_DUE"


def set_state(ingredient, state):
    if ingredient["replenishment_state"] != state:
        ingredient["replenishment_state"] = state
        touch(ingredient)
    return ingredient
