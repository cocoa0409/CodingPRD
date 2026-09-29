"""Product endpoints (PRD 3.1)."""

from flask import Blueprint, request

import serializers
from errors import ApiError
from guards import (
    ANY_ROLE,
    PRODUCTION_METHODS,
    as_allergen_tags,
    as_bool,
    as_decimal,
    as_enum,
    as_int,
    as_object_array,
    as_string,
    authenticate,
    bad,
    body,
    bool_filter,
    enum_filter,
    find_department,
    find_ingredient,
    find_product,
)
from response import created, listing, mark_new, ok, parse_pagination
from store import by_seq, db, new_entity
from util import q2, q4

bp = Blueprint("products", __name__)


def _recipe_ingredient_ids(payload):
    """Ingredient ids as they appear, for the band-4 existence sweep."""
    raw = payload.get("recipe_lines")
    ids = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and isinstance(entry.get("ingredient_id"), str):
                ids.append(entry["ingredient_id"])
            elif isinstance(entry, dict) and "ingredient_id" in entry:
                ids.append(None)
    return ids


@bp.post("/bakery/products")
def create_product():
    authenticate(("RegionalAdmin",))
    payload = body()

    # band 4 -- department first, then every recipe ingredient.
    department = find_department(payload.get("department_id"))
    for ingredient_id in _recipe_ingredient_ids(payload):
        find_ingredient(ingredient_id)

    # band 5 -- request shape.
    sku = as_string(payload, "sku", min_len=1, max_len=20)
    name = as_string(payload, "name", min_len=1, max_len=120)
    method = as_enum(payload, "production_method", PRODUCTION_METHODS)
    units_per_rack = as_int(payload, "units_per_rack", minimum=1, maximum=500)
    proof_minutes = as_int(payload, "proof_minutes", required=False, minimum=0, maximum=600, default=0)
    bake_minutes = as_int(payload, "bake_minutes", required=False, minimum=0, maximum=600, default=0)
    cool_minutes = as_int(payload, "cool_minutes", required=False, minimum=0, maximum=600, default=0)
    base_labor = as_decimal(payload, "base_labor_minutes_per_rack", required=False, minimum=0, default=q2(0))
    setup_labor = as_decimal(payload, "setup_labor_minutes", required=False, minimum=0, default=q2(0))
    unit_retail_cents = as_int(payload, "unit_retail_cents", minimum=1)
    shelf_life_hours = as_int(payload, "shelf_life_hours", minimum=1, maximum=720)
    markdown_pct = as_decimal(payload, "markdown_pct", required=False, minimum=0, maximum=1,
                              exclusive_min=True, exclusive_max=True, default=q4("0.5"))
    allergen_tags = as_allergen_tags(payload, "allergen_tags")
    allergen_free_claim = as_bool(payload, "allergen_free_claim", default=False)
    is_custom_cake_base = as_bool(payload, "is_custom_cake_base", default=False)

    if method == "SCRATCH" and proof_minutes <= 0:
        bad("proof_minutes", "must be greater than 0 for a SCRATCH product.")
    if method != "SCRATCH" and proof_minutes != 0:
        bad("proof_minutes", "must be exactly 0 for a %s product." % method)
    if method in ("SCRATCH", "PAR_BAKED") and bake_minutes <= 0:
        bad("bake_minutes", "must be greater than 0 for a %s product." % method)
    if method == "THAW_AND_SERVE" and bake_minutes != 0:
        bad("bake_minutes", "must be exactly 0 for a THAW_AND_SERVE product.")

    raw_lines = as_object_array(payload, "recipe_lines", required=False)
    recipe_lines = []
    seen = set()
    for entry in raw_lines:
        ingredient_id = entry.get("ingredient_id")
        if not isinstance(ingredient_id, str) or not ingredient_id:
            bad("recipe_lines", "entries require an ingredient_id.")
        line_units = as_int(entry, "units_per_rack", minimum=0)
        if ingredient_id in seen:
            bad("recipe_lines", "may name each ingredient at most once.")
        seen.add(ingredient_id)
        recipe_lines.append({"ingredient_id": ingredient_id, "units_per_rack": line_units})

    # band 11 -- uniqueness inside the department.
    for existing in db.products.values():
        if existing["department_id"] == department["id"] and existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU", "sku already exists in this department.")

    # band 12 -- referential: every ingredient sits in the same department.
    for line in recipe_lines:
        ingredient = find_ingredient(line["ingredient_id"])
        if ingredient["department_id"] != department["id"]:
            raise ApiError("ERR_INGREDIENT_NOT_IN_DEPARTMENT")

    row = new_entity(
        department_id=department["id"],
        sku=sku,
        name=name,
        production_method=method,
        units_per_rack=units_per_rack,
        proof_minutes=proof_minutes,
        bake_minutes=bake_minutes,
        cool_minutes=cool_minutes,
        base_labor_minutes_per_rack=q2(base_labor),
        setup_labor_minutes=q2(setup_labor),
        unit_retail_cents=unit_retail_cents,
        shelf_life_hours=shelf_life_hours,
        markdown_pct=q4(markdown_pct),
        allergen_tags=allergen_tags,
        allergen_free_claim=allergen_free_claim,
        recipe_lines=recipe_lines,
        is_custom_cake_base=is_custom_cake_base,
    )
    db.products[row["id"]] = row
    mark_new(row)
    return created(serializers.product(row))


@bp.get("/bakery/products/<productId>")
def read_product(productId):
    authenticate(ANY_ROLE)
    return ok(serializers.product(find_product(productId)))


@bp.get("/bakery/products")
def list_products():
    authenticate(ANY_ROLE)
    limit, offset = parse_pagination(request.args)
    department_id = request.args.get("department_id") or None
    method = enum_filter(request.args, "production_method", PRODUCTION_METHODS)
    custom_base = bool_filter(request.args, "is_custom_cake_base")
    rows = []
    for row in db.products.values():
        if department_id is not None and row["department_id"] != department_id:
            continue
        if method is not None and row["production_method"] != method:
            continue
        if custom_base is not None and row["is_custom_cake_base"] != custom_base:
            continue
        rows.append(row)
    return listing([serializers.product(row) for row in by_seq(rows)], limit, offset)
