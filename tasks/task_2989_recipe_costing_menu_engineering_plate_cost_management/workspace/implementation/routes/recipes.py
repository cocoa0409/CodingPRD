"""Recipes, components, roll-up, review lifecycle and prep guides
(PRD 3.3, 3.4)."""
from flask import Blueprint

import serial
from cascade import propagate_upward, stale_menu_items_of
from core import (
    COST_BASES, MAX_RECIPE_DEPTH, UOMS, db, order_key, stamp_new, touch,
)
from envelope import created, listing, ok
from errors import fail
from graph import (
    active_components, ap_from_ep, apply_profile, cost_rollup, depth_of,
    menu_items_of, nutrition_profile, parents_of, prep_guide_of, reaches,
)
from guards import (
    ANY_ROLE, authenticate, find_component, find_ingredient, find_recipe,
    get_body, opt_enum, opt_id, pagination, paginate, query_enum, query_str,
    req_enum, req_int, req_str,
)

bp = Blueprint("recipes", __name__)

RECIPE_CODE = r"^[A-Z0-9-]{3,20}$"
MUTABLE_STATUSES = ("DRAFT", "UNDER_REVIEW")


def _sort_components(rows):
    return sorted(rows, key=lambda c: (c["sequence_no"], c["created_at"], c["_seq"]))


def _all_ancestors(recipe_id):
    found = []
    queue = [recipe_id]
    seen = set()
    while queue:
        current = queue.pop(0)
        for parent_id in sorted(parents_of(current)):
            if parent_id in seen:
                continue
            seen.add(parent_id)
            found.append(parent_id)
            queue.append(parent_id)
    return found


def _spec_changed(recipe):
    """The shared invalidation after a direct component edit (PRD 3.3)."""
    apply_profile(recipe)
    recipe["cost_state"] = "STALE"
    touch(recipe)
    ancestors = propagate_upward([recipe["id"]])
    stale_menu_items_of([recipe["id"]] + ancestors)


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------
@bp.post("/culinary/recipes")
def create_recipe():
    authenticate(("RecipeDeveloper",))
    body = get_body()
    code = req_str(body, "code", pattern=RECIPE_CODE, min_len=None)
    name = req_str(body, "name", min_len=1, max_len=80)
    recipe_type = req_enum(body, "recipe_type", ("SUB_RECIPE", "PLATED"))
    base_uom = req_enum(body, "base_uom", UOMS)
    batch_yield = req_int(body, "batch_yield_base_units", minimum=1)
    portions = req_int(body, "portions_per_batch", minimum=1)
    for existing in db.recipes.values():
        if existing["code"] == code:
            fail("ERR_DUPLICATE_CODE", "Recipe code %s already exists." % code)
    row = stamp_new({
        "code": code,
        "name": name,
        "recipe_type": recipe_type,
        "base_uom": base_uom,
        "batch_yield_base_units": batch_yield,
        "portions_per_batch": portions,
        "status": "DRAFT",
        "cost_state": "STALE",
        "cost_basis": None,
        "batch_cost_micros": 0,
        "portion_cost_micros": 0,
        "allergen_mask": 0,
        "kcal_per_portion_micros": 0,
        "sodium_mcg_per_portion": 0,
        "depth": 0,
        "component_count": 0,
        "open_spec_change_count": 0,
        "last_rollup_at": None,
    })
    db.recipes[row["id"]] = row
    return created(serial.recipe(row))


@bp.get("/culinary/recipes/<recipe_id>")
def get_recipe(recipe_id):
    authenticate(ANY_ROLE)
    return ok(serial.recipe(find_recipe(recipe_id)))


@bp.get("/culinary/recipes/<recipe_id>/allergen-nutrition")
def recipe_allergen_nutrition(recipe_id):
    authenticate(ANY_ROLE)
    recipe = find_recipe(recipe_id)
    payload = serial.recipe(recipe)
    payload.update(nutrition_profile(recipe))
    return ok(payload)


@bp.get("/culinary/recipes/<recipe_id>/prep-guides")
def list_prep_guides(recipe_id):
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    find_recipe(recipe_id)
    rows = sorted([g for g in db.prep_guides.values() if g["recipe_id"] == recipe_id],
                  key=order_key)
    page, limit, offset, total = paginate(rows, limit, offset, serial.prep_guide)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------
@bp.post("/culinary/recipes/<recipe_id>/components")
def create_component(recipe_id):
    authenticate(("RecipeDeveloper",))
    body = get_body()
    component_type = req_enum(body, "component_type", ("INGREDIENT", "SUB_RECIPE"))
    ingredient_id = opt_id(body, "ingredient_id")
    child_recipe_id = opt_id(body, "child_recipe_id")
    ep_quantity = req_int(body, "ep_quantity_base_units", minimum=1)
    sequence_no = req_int(body, "sequence_no", minimum=1)
    expected_recipe_version = req_int(body, "expected_recipe_version")
    if component_type == "INGREDIENT":
        if ingredient_id is None or child_recipe_id is not None:
            fail("ERR_INVALID_REQUEST",
                 "An INGREDIENT component requires ingredient_id and a null child_recipe_id.")
    else:
        if child_recipe_id is None or ingredient_id is not None:
            fail("ERR_INVALID_REQUEST",
                 "A SUB_RECIPE component requires child_recipe_id and a null ingredient_id.")

    recipe = find_recipe(recipe_id)
    ingredient = None
    child = None
    if component_type == "INGREDIENT":
        ingredient = find_ingredient(ingredient_id)
    else:
        child = find_recipe(child_recipe_id)

    # 15 -- optimistic concurrency on the parent recipe.
    if expected_recipe_version != recipe["version"]:
        fail("ERR_STALE_RECIPE_VERSION",
             "expected_recipe_version %s does not match the stored version %s."
             % (expected_recipe_version, recipe["version"]))

    # 17 -- the component set is only editable in DRAFT or UNDER_REVIEW.
    if recipe["status"] not in MUTABLE_STATUSES:
        fail("ERR_RECIPE_NOT_MUTABLE",
             "A %s recipe's component set cannot be edited directly." % recipe["status"])

    # 31 -- no retired ingredient may be added.
    if ingredient is not None and ingredient["status"] != "ACTIVE":
        fail("ERR_INGREDIENT_RETIRED", "The ingredient is RETIRED.")

    # 34 -- no cycle.
    if child is not None and reaches(child["id"], recipe["id"]):
        fail("ERR_RECIPE_CYCLE", "The component would close a cycle in the recipe graph.")

    row = stamp_new({
        "recipe_id": recipe["id"],
        "component_type": component_type,
        "ingredient_id": ingredient_id,
        "child_recipe_id": child_recipe_id,
        "ep_quantity_base_units": ep_quantity,
        "ap_quantity_base_units": (ap_from_ep(ep_quantity, ingredient["net_yield_bps"])
                                  if ingredient is not None else ep_quantity),
        "unit_cost_micros_used": 0,
        "pack_base_units_snapshot": 0,
        "extended_cost_micros": 0,
        "sequence_no": sequence_no,
        "status": "ACTIVE",
        "removed_at": None,
    })
    db.recipe_components[row["id"]] = row

    # 35 -- the resulting depth of this recipe and of every recipe above it.
    if child is not None:
        offenders = [recipe["id"]] + _all_ancestors(recipe["id"])
        for candidate_id in offenders:
            if depth_of(candidate_id) > MAX_RECIPE_DEPTH:
                del db.recipe_components[row["id"]]
                fail("ERR_RECIPE_DEPTH_EXCEEDED",
                     "The resulting nesting depth exceeds %d." % MAX_RECIPE_DEPTH)

    _spec_changed(recipe)
    return created(serial.recipe_component(row))


@bp.get("/culinary/recipe-components/<recipe_component_id>")
def get_component(recipe_component_id):
    authenticate(ANY_ROLE)
    return ok(serial.recipe_component(find_component(recipe_component_id)))


@bp.get("/culinary/recipe-components")
def list_components():
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    status = query_enum("status", ("ACTIVE", "REMOVED"))
    recipe_id = query_str("recipe_id")
    child_recipe_id = query_str("child_recipe_id")
    ingredient_id = query_str("ingredient_id")
    rows = list(db.recipe_components.values())
    if recipe_id is not None:
        rows = [c for c in rows if c["recipe_id"] == recipe_id]
    if child_recipe_id is not None:
        rows = [c for c in rows if c["child_recipe_id"] == child_recipe_id]
    if ingredient_id is not None:
        rows = [c for c in rows if c["ingredient_id"] == ingredient_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    page, limit, offset, total = paginate(_sort_components(rows), limit, offset,
                                         serial.recipe_component)
    return listing(page, limit, offset, total)


@bp.delete("/culinary/recipe-components/<recipe_component_id>")
def delete_component(recipe_component_id):
    authenticate(("RecipeDeveloper",))
    body = get_body()
    expected_recipe_version = req_int(body, "expected_recipe_version")
    component = find_component(recipe_component_id)
    recipe = db.recipes.get(component["recipe_id"])
    if recipe is None:
        fail("ERR_RECIPE_NOT_FOUND", "The owning recipe no longer exists.")
    if expected_recipe_version != recipe["version"]:
        fail("ERR_STALE_RECIPE_VERSION",
             "expected_recipe_version %s does not match the stored version %s."
             % (expected_recipe_version, recipe["version"]))
    if recipe["status"] not in MUTABLE_STATUSES:
        fail("ERR_RECIPE_NOT_MUTABLE",
             "A %s recipe's component set cannot be edited directly." % recipe["status"])
    if component["status"] != "ACTIVE":
        fail("ERR_COMPONENT_ALREADY_REMOVED", "The component is already REMOVED.")
    component["status"] = "REMOVED"
    component["removed_at"] = db.now()
    touch(component)
    _spec_changed(recipe)
    return ok(serial.recipe_component(component))


# ---------------------------------------------------------------------------
# Roll-up and lifecycle
# ---------------------------------------------------------------------------
@bp.post("/culinary/recipes/<recipe_id>/cost-rollup")
def rollup(recipe_id):
    authenticate(("CostAnalyst",))
    body = get_body()
    basis = opt_enum(body, "basis", COST_BASES, default="LATEST_PUBLISHED")
    recipe = find_recipe(recipe_id)
    cost_rollup(recipe, basis)
    return ok(serial.recipe(recipe))


@bp.post("/culinary/recipes/<recipe_id>/submit-review")
def submit_review(recipe_id):
    authenticate(("RecipeDeveloper",))
    recipe = find_recipe(recipe_id)
    if recipe["status"] not in ("DRAFT", "ACTIVE"):
        fail("ERR_RECIPE_INVALID_STATE",
             "A %s recipe cannot be submitted for review." % recipe["status"])
    if not active_components(recipe["id"]):
        fail("ERR_RECIPE_INVALID_STATE",
             "A recipe with no active components is not reviewable.")
    if recipe["cost_state"] != "FRESH":
        fail("ERR_COST_STALE", "The recipe cost is STALE.")
    if depth_of(recipe["id"]) > MAX_RECIPE_DEPTH:
        fail("ERR_RECIPE_DEPTH_EXCEEDED",
             "The recipe nests deeper than %d." % MAX_RECIPE_DEPTH)
    recipe["status"] = "UNDER_REVIEW"
    touch(recipe)
    return ok(serial.recipe(recipe))


@bp.post("/culinary/recipes/<recipe_id>/activate")
def activate_recipe(recipe_id):
    authenticate(("CulinaryDirector",))
    recipe = find_recipe(recipe_id)
    if recipe["status"] != "UNDER_REVIEW":
        fail("ERR_RECIPE_INVALID_STATE",
             "Only an UNDER_REVIEW recipe can be activated.")
    if recipe["cost_state"] != "FRESH":
        fail("ERR_COST_STALE", "The recipe cost is STALE.")
    components = active_components(recipe["id"])
    for component in components:
        if component["component_type"] != "SUB_RECIPE":
            continue
        child = db.recipes.get(component["child_recipe_id"])
        if child is None or child["status"] != "ACTIVE":
            fail("ERR_SUBRECIPE_NOT_ACTIVE",
                 "Sub-recipe component %s does not point at an ACTIVE recipe."
                 % component["id"])
    for component in components:
        if component["component_type"] != "INGREDIENT":
            continue
        ingredient = db.ingredients.get(component["ingredient_id"])
        if ingredient is None or ingredient["status"] != "ACTIVE":
            fail("ERR_INGREDIENT_RETIRED",
                 "Component %s references a RETIRED ingredient." % component["id"])
    if depth_of(recipe["id"]) > MAX_RECIPE_DEPTH:
        fail("ERR_RECIPE_DEPTH_EXCEEDED",
             "The recipe nests deeper than %d." % MAX_RECIPE_DEPTH)

    recipe["status"] = "ACTIVE"
    touch(recipe)
    if prep_guide_of(recipe["id"]) is None:
        guide = stamp_new({
            "recipe_id": recipe["id"],
            "revision_no": 1,
            "sync_state": "CURRENT",
            "batch_yield_base_units_snapshot": recipe["batch_yield_base_units"],
            "portions_per_batch_snapshot": recipe["portions_per_batch"],
            "component_count_snapshot": recipe["component_count"],
            "synced_spec_version": recipe["version"],
        })
        db.prep_guides[guide["id"]] = guide
    return ok(serial.recipe(recipe))


@bp.post("/culinary/recipes/<recipe_id>/retire")
def retire_recipe(recipe_id):
    authenticate(("CulinaryDirector",))
    recipe = find_recipe(recipe_id)
    if recipe["status"] != "ACTIVE":
        fail("ERR_RECIPE_INVALID_STATE", "Only an ACTIVE recipe can be retired.")
    for component in db.recipe_components.values():
        if (component["status"] != "ACTIVE"
                or component["component_type"] != "SUB_RECIPE"
                or component["child_recipe_id"] != recipe["id"]):
            continue
        parent = db.recipes.get(component["recipe_id"])
        if parent is not None and parent["status"] in ("DRAFT", "UNDER_REVIEW", "ACTIVE"):
            fail("ERR_RECIPE_INVALID_STATE",
                 "Recipe %s still consumes this recipe as a sub-recipe." % parent["id"])
    for item in menu_items_of(recipe["id"]):
        if item["status"] in ("DRAFT", "ACTIVE"):
            fail("ERR_MENU_ITEM_INVALID_STATE",
                 "Menu item %s still depends on this recipe." % item["id"])
    recipe["status"] = "RETIRED"
    recipe["cost_state"] = "STALE"
    touch(recipe)
    return ok(serial.recipe(recipe))
