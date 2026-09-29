"""Ingredient order endpoints: case-pack costing under optimistic concurrency,
submission, the branching receipt and cancellation (PRD 3.8)."""

from flask import Blueprint, request

import serializers
from errors import ApiError
from guards import (
    ANY_ROLE,
    INGREDIENT_ORDER_ORIGINS,
    INGREDIENT_ORDER_STATUSES,
    as_int,
    as_object_array,
    as_string,
    authenticate,
    bad,
    body,
    enum_filter,
    find_bake_day,
    find_department,
    find_ingredient,
    find_ingredient_order,
    scope,
)
from response import created, listing, ok, parse_pagination, touch
from services.calc import shelf_life_cap
from services.purchasing import build_lines, create_order
from services.rollups import derive_state_on_hand, recompute_commitment, set_state
from store import by_seq, db

bp = Blueprint("ingredient_orders", __name__)


def _line_ingredient_ids(payload):
    """Line ingredient ids as they appear, for the band-4 existence sweep."""
    raw = payload.get("lines")
    ids = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and isinstance(entry.get("ingredient_id"), str):
                ids.append(entry["ingredient_id"])
            elif isinstance(entry, dict) and "ingredient_id" in entry:
                ids.append(None)
    return ids


@bp.post("/bakery/ingredient-orders")
def create_ingredient_order():
    caller = authenticate(("DepartmentManager",))
    payload = body()

    # band 4 -- department, then the optional target day, then every line.
    department = find_department(payload.get("department_id"))
    scope(caller, department["id"])
    target_bake_day_id = None
    if payload.get("target_bake_day_id") is not None:
        target_bake_day_id = find_bake_day(payload.get("target_bake_day_id"))["id"]
    for ingredient_id in _line_ingredient_ids(payload):
        find_ingredient(ingredient_id)

    # band 5 -- request shape.
    expected = as_int(payload, "expected_department_version", minimum=0)
    raw_lines = as_object_array(payload, "lines")
    entries = []
    seen = set()
    for entry in raw_lines:
        ingredient_id = entry.get("ingredient_id")
        if not isinstance(ingredient_id, str) or not ingredient_id:
            bad("lines", "entries require an ingredient_id.")
        required_units = as_int(entry, "required_units", minimum=1)
        if ingredient_id in seen:
            bad("lines", "may name each ingredient at most once.")
        seen.add(ingredient_id)
        entries.append((ingredient_id, required_units))

    # band 6 -- optimistic concurrency on the department.
    if expected != department["version"]:
        raise ApiError("ERR_STALE_DEPARTMENT_VERSION")

    # band 12 -- referential: every ingredient sits in the ordering department.
    resolved = []
    for ingredient_id, required_units in entries:
        ingredient = find_ingredient(ingredient_id)
        if ingredient["department_id"] != department["id"]:
            raise ApiError("ERR_INGREDIENT_NOT_IN_DEPARTMENT")
        resolved.append((ingredient, required_units))

    # band 13 -- the shelf-life cap, tested against the post-rounding quantity.
    lines, total = build_lines(department, resolved)
    for ingredient, line in zip([pair[0] for pair in resolved], lines):
        if line["ordered_units"] > shelf_life_cap(ingredient):
            raise ApiError("ERR_SHELF_LIFE_OVERSTOCK")

    order = create_order(department, target_bake_day_id, "MANUAL", lines, total)
    recompute_commitment(department, force=True)
    return created(serializers.ingredient_order(order))


@bp.get("/bakery/ingredient-orders/<ingredientOrderId>")
def read_ingredient_order(ingredientOrderId):
    authenticate(ANY_ROLE)
    return ok(serializers.ingredient_order(find_ingredient_order(ingredientOrderId)))


@bp.get("/bakery/ingredient-orders")
def list_ingredient_orders():
    authenticate(ANY_ROLE)
    limit, offset = parse_pagination(request.args)
    department_id = request.args.get("department_id") or None
    target_bake_day_id = request.args.get("target_bake_day_id") or None
    status = enum_filter(request.args, "order_status", INGREDIENT_ORDER_STATUSES)
    origin = enum_filter(request.args, "origin", INGREDIENT_ORDER_ORIGINS)
    rows = []
    for row in db.ingredient_orders.values():
        if department_id is not None and row["department_id"] != department_id:
            continue
        if target_bake_day_id is not None and row["target_bake_day_id"] != target_bake_day_id:
            continue
        if status is not None and row["order_status"] != status:
            continue
        if origin is not None and row["origin"] != origin:
            continue
        rows.append(row)
    return listing([serializers.ingredient_order(row) for row in by_seq(rows)], limit, offset)


@bp.post("/bakery/ingredient-orders/<ingredientOrderId>/submit")
def submit_order(ingredientOrderId):
    caller = authenticate(("DepartmentManager",))
    order = find_ingredient_order(ingredientOrderId)
    department = db.departments.get(order["department_id"])
    scope(caller, order["department_id"])

    if order["order_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_INGREDIENT_ORDER_STATE", "Only a DRAFT order may be submitted.")
    if not order["lines"]:
        raise ApiError("ERR_INVALID_REQUEST", "An order with no line may not be submitted.")

    order["order_status"] = "SUBMITTED"
    order["submitted_at_utc"] = db.now()
    touch(order)

    # every named ingredient goes on order, in lines array order.
    for line in order["lines"]:
        ingredient = db.ingredients.get(line["ingredient_id"])
        if ingredient is None:
            continue
        if ingredient["replenishment_state"] in ("OK", "REORDER_DUE"):
            set_state(ingredient, "ON_ORDER")

    # DRAFT and SUBMITTED both count: the commitment is deliberately unchanged.
    if department is not None:
        recompute_commitment(department)
    return ok(serializers.ingredient_order(order))


@bp.post("/bakery/ingredient-orders/<ingredientOrderId>/receive")
def receive_order(ingredientOrderId):
    caller = authenticate(("Baker", "DepartmentManager"))
    order = find_ingredient_order(ingredientOrderId)
    department = db.departments.get(order["department_id"])
    scope(caller, order["department_id"])
    payload = body()

    raw_received = as_object_array(payload, "received_lines")
    ordered_ids = [line["ingredient_id"] for line in order["lines"]]

    # band 4 -- every receipt entry must name a line of this order.
    for entry in raw_received:
        ingredient_id = entry.get("ingredient_id")
        if not isinstance(ingredient_id, str) or ingredient_id not in ordered_ids:
            raise ApiError("ERR_INGREDIENT_NOT_FOUND", "The order carries no line for this ingredient.")

    # band 5 -- shape, then full coverage of the order's lines.
    received_lines = []
    received_by_id = {}
    for entry in raw_received:
        ingredient_id = entry["ingredient_id"]
        received_units = as_int(entry, "received_units", minimum=0)
        received_by_id[ingredient_id] = received_units
        received_lines.append({"ingredient_id": ingredient_id, "received_units": received_units})
    for ingredient_id in ordered_ids:
        if ingredient_id not in received_by_id:
            bad("received_lines", "must carry an entry for every line of the order.")

    # band 7 -- own-entity state.
    if order["order_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_INGREDIENT_ORDER_STATE", "Only a SUBMITTED order may be received.")

    shortfall = 0
    for line in order["lines"]:
        received_units = int(received_by_id[line["ingredient_id"]])
        gap = int(line["ordered_units"]) - received_units
        if gap > 0:
            shortfall += gap
        ingredient = db.ingredients.get(line["ingredient_id"])
        if ingredient is None:
            continue
        ingredient["on_hand_units"] = int(ingredient["on_hand_units"]) + received_units
        touch(ingredient)
        set_state(ingredient, derive_state_on_hand(ingredient))

    order["received_lines"] = received_lines
    order["shortfall_units_total"] = shortfall
    order["order_status"] = "RECEIVED_FULL" if shortfall == 0 else "RECEIVED_SHORT"
    touch(order)

    if department is not None:
        recompute_commitment(department, force=True)
    return ok(serializers.ingredient_order(order))


@bp.post("/bakery/ingredient-orders/<ingredientOrderId>/cancel")
def cancel_order(ingredientOrderId):
    caller = authenticate(("DepartmentManager",))
    order = find_ingredient_order(ingredientOrderId)
    department = db.departments.get(order["department_id"])
    scope(caller, order["department_id"])
    payload = body()
    cancel_reason = as_string(payload, "cancel_reason", min_len=1, max_len=500)

    if order["order_status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_INVALID_INGREDIENT_ORDER_STATE", "The order has already reached a terminal state.")

    order["cancel_reason"] = cancel_reason
    order["order_status"] = "CANCELLED"
    touch(order)

    if department is not None:
        recompute_commitment(department, force=True)

    # the compensating half releases every ingredient that was ON_ORDER.
    for line in order["lines"]:
        ingredient = db.ingredients.get(line["ingredient_id"])
        if ingredient is None:
            continue
        set_state(ingredient, derive_state_on_hand(ingredient))
    return ok(serializers.ingredient_order(order))
