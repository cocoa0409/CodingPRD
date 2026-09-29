"""Ingredient endpoints (PRD 3.1)."""

from flask import Blueprint, request

import serializers
from errors import ApiError
from guards import (
    ANY_ROLE,
    REPLENISHMENT_STATES,
    as_allergen_tags,
    as_decimal,
    as_int,
    as_string,
    authenticate,
    body,
    enum_filter,
    find_department,
    find_ingredient,
)
from response import created, listing, mark_new, ok, parse_pagination
from store import by_seq, db, new_entity
from util import q2

bp = Blueprint("ingredients", __name__)


@bp.post("/bakery/ingredients")
def create_ingredient():
    authenticate(("RegionalAdmin",))
    payload = body()
    department = find_department(payload.get("department_id"))

    name = as_string(payload, "name", min_len=1, max_len=120)
    case_pack_units = as_int(payload, "case_pack_units", minimum=1, maximum=1000)
    unit_cost_cents = as_decimal(payload, "unit_cost_cents", minimum=0, exclusive_min=True)
    shelf_life_days = as_int(payload, "shelf_life_days", minimum=1, maximum=3650)
    daily_usage_units = as_int(payload, "daily_usage_units", minimum=1)
    reorder_point_units = as_int(payload, "reorder_point_units", minimum=0)
    on_hand_units = as_int(payload, "on_hand_units", required=False, minimum=0, default=0)
    allergen_tags = as_allergen_tags(payload, "allergen_tags")

    for existing in db.ingredients.values():
        if existing["department_id"] == department["id"] and existing["name"] == name:
            raise ApiError("ERR_DUPLICATE_SKU", "name already exists in this department.")

    state = "OK" if on_hand_units >= reorder_point_units else "REORDER_DUE"
    row = new_entity(
        department_id=department["id"],
        name=name,
        case_pack_units=case_pack_units,
        unit_cost_cents=q2(unit_cost_cents),
        shelf_life_days=shelf_life_days,
        daily_usage_units=daily_usage_units,
        reorder_point_units=reorder_point_units,
        on_hand_units=on_hand_units,
        replenishment_state=state,
        allergen_tags=allergen_tags,
    )
    db.ingredients[row["id"]] = row
    mark_new(row)
    return created(serializers.ingredient(row))


@bp.get("/bakery/ingredients/<ingredientId>")
def read_ingredient(ingredientId):
    authenticate(ANY_ROLE)
    return ok(serializers.ingredient(find_ingredient(ingredientId)))


@bp.get("/bakery/ingredients")
def list_ingredients():
    authenticate(ANY_ROLE)
    limit, offset = parse_pagination(request.args)
    department_id = request.args.get("department_id") or None
    state = enum_filter(request.args, "replenishment_state", REPLENISHMENT_STATES)
    rows = []
    for row in db.ingredients.values():
        if department_id is not None and row["department_id"] != department_id:
            continue
        if state is not None and row["replenishment_state"] != state:
            continue
        rows.append(row)
    return listing([serializers.ingredient(row) for row in by_seq(rows)], limit, offset)
