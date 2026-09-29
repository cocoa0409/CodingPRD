"""Specification change orders: approval, the four-hop cascade, rollback and
propagation (PRD 3.6)."""
from flask import Blueprint

import serial
from calc import refresh_count_line
from cascade import (
    mark_count_lines_out_of_date, mark_prep_guide_out_of_date, propagate_upward,
    stale_menu_items_of,
)
from core import db, order_key, stamp_new, touch
from envelope import created, listing, ok
from errors import fail
from graph import ap_from_ep, apply_profile, prep_guide_of
from guards import (
    ANY_ROLE, authenticate, find_component, find_ingredient, find_order,
    find_recipe, get_body, opt_id, opt_int, pagination, paginate, query_enum,
    query_str, req_enum, req_id, req_int, req_str, require_null,
)

bp = Blueprint("spec_orders", __name__)

CHANGE_TYPES = ("COMPONENT_QTY", "COMPONENT_ADD", "COMPONENT_REMOVE")
APPROVAL_STATUSES = ("DRAFT", "PENDING", "APPROVED", "REJECTED", "ROLLED_BACK")
PROPAGATION_STATUSES = ("NOT_STARTED", "PREP_GUIDE_SYNCED", "COUNTS_SYNCED",
                        "FULLY_PROPAGATED")


@bp.post("/culinary/spec-change-orders")
def create_order():
    authenticate(("RecipeDeveloper",))
    body = get_body()
    recipe_id = req_id(body, "recipe_id")
    change_type = req_enum(body, "change_type", CHANGE_TYPES)
    target_component_id = opt_id(body, "target_component_id")
    ingredient_id = opt_id(body, "ingredient_id")
    new_ep_quantity = opt_int(body, "new_ep_quantity_base_units", minimum=1)
    expected_recipe_version = req_int(body, "expected_recipe_version")

    if change_type == "COMPONENT_QTY":
        if target_component_id is None or new_ep_quantity is None:
            fail("ERR_INVALID_REQUEST",
                 "COMPONENT_QTY requires target_component_id and "
                 "new_ep_quantity_base_units.")
        require_null(body, "ingredient_id")
    elif change_type == "COMPONENT_ADD":
        if ingredient_id is None or new_ep_quantity is None:
            fail("ERR_INVALID_REQUEST",
                 "COMPONENT_ADD requires ingredient_id and "
                 "new_ep_quantity_base_units.")
        require_null(body, "target_component_id")
    else:
        if target_component_id is None:
            fail("ERR_INVALID_REQUEST", "COMPONENT_REMOVE requires target_component_id.")
        require_null(body, "ingredient_id")
        require_null(body, "new_ep_quantity_base_units")

    # 5 -- body ingredient, then 7 -- recipe, then 8 -- target component.
    if ingredient_id is not None:
        find_ingredient(ingredient_id)
    recipe = find_recipe(recipe_id)
    target = None
    if target_component_id is not None:
        target = find_component(target_component_id)

    # 15 -- the author must have read this specification.
    if expected_recipe_version != recipe["version"]:
        fail("ERR_STALE_RECIPE_VERSION",
             "expected_recipe_version %s does not match the stored version %s."
             % (expected_recipe_version, recipe["version"]))
    # 18 -- change orders exist only for live specifications.
    if recipe["status"] != "ACTIVE":
        fail("ERR_RECIPE_INVALID_STATE",
             "A specification change order requires an ACTIVE recipe.")
    # 28 -- the targeted line must still be there.
    if target is not None and target["status"] != "ACTIVE":
        fail("ERR_COMPONENT_ALREADY_REMOVED", "The target component is already REMOVED.")

    row = stamp_new({
        "recipe_id": recipe["id"],
        "change_type": change_type,
        "target_component_id": target_component_id,
        "ingredient_id": ingredient_id,
        "new_ep_quantity_base_units": new_ep_quantity,
        "approval_status": "DRAFT",
        "propagation_status": "NOT_STARTED",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "rejection_reason": None,
        "created_component_id": None,
        "pre_change_ep_quantity_base_units": None,
        "pre_change_batch_cost_micros": None,
        "pre_change_allergen_mask": None,
        "pre_change_recipe_version": None,
        "approved_at": None,
    })
    db.spec_change_orders[row["id"]] = row
    recipe["open_spec_change_count"] = recipe["open_spec_change_count"] + 1
    touch(recipe)
    return created(serial.spec_change_order(row))


@bp.get("/culinary/spec-change-orders/<spec_change_order_id>")
def get_order(spec_change_order_id):
    authenticate(ANY_ROLE)
    return ok(serial.spec_change_order(find_order(spec_change_order_id)))


@bp.get("/culinary/spec-change-orders")
def list_orders():
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    approval_status = query_enum("approval_status", APPROVAL_STATUSES)
    propagation_status = query_enum("propagation_status", PROPAGATION_STATUSES)
    recipe_id = query_str("recipe_id")
    target_component_id = query_str("target_component_id")
    ingredient_id = query_str("ingredient_id")
    rows = list(db.spec_change_orders.values())
    if recipe_id is not None:
        rows = [o for o in rows if o["recipe_id"] == recipe_id]
    if target_component_id is not None:
        rows = [o for o in rows if o["target_component_id"] == target_component_id]
    if ingredient_id is not None:
        rows = [o for o in rows if o["ingredient_id"] == ingredient_id]
    if approval_status is not None:
        rows = [o for o in rows if o["approval_status"] == approval_status]
    if propagation_status is not None:
        rows = [o for o in rows if o["propagation_status"] == propagation_status]
    rows.sort(key=order_key)
    page, limit, offset, total = paginate(rows, limit, offset, serial.spec_change_order)
    return listing(page, limit, offset, total)


@bp.post("/culinary/spec-change-orders/<spec_change_order_id>/submit")
def submit_order(spec_change_order_id):
    user_id, _role = authenticate(("RecipeDeveloper",))
    order = find_order(spec_change_order_id)
    if order["approval_status"] != "DRAFT":
        fail("ERR_SCO_INVALID_STATE", "Only a DRAFT order can be submitted.")
    if order["change_type"] in ("COMPONENT_QTY", "COMPONENT_REMOVE"):
        target = db.recipe_components.get(order["target_component_id"])
        if target is None or target["status"] != "ACTIVE":
            fail("ERR_COMPONENT_ALREADY_REMOVED",
                 "The target component is already REMOVED.")
    order["approval_status"] = "PENDING"
    order["submitted_by_user_id"] = user_id
    touch(order)
    return ok(serial.spec_change_order(order))


@bp.post("/culinary/spec-change-orders/<spec_change_order_id>/reject")
def reject_order(spec_change_order_id):
    authenticate(("CulinaryDirector",))
    body = get_body()
    reason = req_str(body, "rejection_reason", min_len=None)
    order = find_order(spec_change_order_id)
    if order["approval_status"] != "PENDING":
        fail("ERR_SCO_INVALID_STATE", "Only a PENDING order can be rejected.")
    order["approval_status"] = "REJECTED"
    order["rejection_reason"] = reason
    touch(order)
    recipe = db.recipes.get(order["recipe_id"])
    if recipe is not None:
        recipe["open_spec_change_count"] = max(0, recipe["open_spec_change_count"] - 1)
        touch(recipe)
    return ok(serial.spec_change_order(order))


@bp.post("/culinary/spec-change-orders/<spec_change_order_id>/approve")
def approve_order(spec_change_order_id):
    user_id, _role = authenticate(("CulinaryDirector",))
    order = find_order(spec_change_order_id)
    # 22 -- the approval dimension.
    if order["approval_status"] != "PENDING":
        fail("ERR_SCO_INVALID_STATE", "Only a PENDING order can be approved.")
    recipe = db.recipes.get(order["recipe_id"])
    if recipe is None:
        fail("ERR_RECIPE_NOT_FOUND", "The owning recipe no longer exists.")
    # 18 -- deliberately ahead of the segregation-of-duties comparison.
    if recipe["status"] != "ACTIVE":
        fail("ERR_RECIPE_INVALID_STATE", "The owning recipe is no longer ACTIVE.")
    # 27 -- segregation of duties.
    if user_id == order["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The approver must differ from the submitter.")
    # 28 -- the target line must survive.
    target = None
    if order["change_type"] in ("COMPONENT_QTY", "COMPONENT_REMOVE"):
        target = db.recipe_components.get(order["target_component_id"])
        if target is None or target["status"] != "ACTIVE":
            fail("ERR_COMPONENT_ALREADY_REMOVED",
                 "The target component is already REMOVED.")
    # 31 -- an addition may not introduce a retired ingredient.
    ingredient = None
    if order["change_type"] == "COMPONENT_ADD":
        ingredient = db.ingredients.get(order["ingredient_id"])
        if ingredient is None or ingredient["status"] != "ACTIVE":
            fail("ERR_INGREDIENT_RETIRED", "The referenced ingredient is RETIRED.")

    # --- Snapshots, taken before anything moves.
    order["pre_change_batch_cost_micros"] = recipe["batch_cost_micros"]
    order["pre_change_allergen_mask"] = recipe["allergen_mask"]
    order["pre_change_recipe_version"] = recipe["version"]
    order["pre_change_ep_quantity_base_units"] = (
        target["ep_quantity_base_units"] if target is not None else None)
    order["approved_by_user_id"] = user_id
    order["approved_at"] = db.now()
    order["approval_status"] = "APPROVED"

    # --- Hop 1: the specification edit. No cost figure is recomputed here.
    if order["change_type"] == "COMPONENT_QTY":
        component_ingredient = db.ingredients.get(target["ingredient_id"])
        target["ep_quantity_base_units"] = order["new_ep_quantity_base_units"]
        if component_ingredient is not None:
            target["ap_quantity_base_units"] = ap_from_ep(
                target["ep_quantity_base_units"],
                component_ingredient["net_yield_bps"])
        else:
            target["ap_quantity_base_units"] = target["ep_quantity_base_units"]
        touch(target)
    elif order["change_type"] == "COMPONENT_ADD":
        component = stamp_new({
            "recipe_id": recipe["id"],
            "component_type": "INGREDIENT",
            "ingredient_id": order["ingredient_id"],
            "child_recipe_id": None,
            "ep_quantity_base_units": order["new_ep_quantity_base_units"],
            "ap_quantity_base_units": ap_from_ep(
                order["new_ep_quantity_base_units"], ingredient["net_yield_bps"]),
            "unit_cost_micros_used": 0,
            "pack_base_units_snapshot": 0,
            "extended_cost_micros": 0,
            "sequence_no": recipe["component_count"] + 1,
            "status": "ACTIVE",
            "removed_at": None,
        })
        db.recipe_components[component["id"]] = component
        order["created_component_id"] = component["id"]
    else:
        target["status"] = "REMOVED"
        target["removed_at"] = db.now()
        touch(target)
    touch(order)

    # --- Hop 2: the recipe, its ancestors and the propagation queue.
    apply_profile(recipe)
    recipe["cost_state"] = "STALE"
    recipe["open_spec_change_count"] = max(0, recipe["open_spec_change_count"] - 1)
    touch(recipe)
    ancestors = propagate_upward([recipe["id"]])
    mark_prep_guide_out_of_date(recipe["id"])
    mark_count_lines_out_of_date(recipe["id"])

    # --- Hops 3 and 4: the menu items, and the promotions priced off them.
    stale_menu_items_of([recipe["id"]] + ancestors, source_recipe=recipe)

    return ok(serial.spec_change_order(order))


@bp.post("/culinary/spec-change-orders/<spec_change_order_id>/propagate")
def propagate_order(spec_change_order_id):
    authenticate(("CostAnalyst",))
    body = get_body()
    target = req_enum(body, "target", ("PREP_GUIDE", "COUNT_SHEETS"))
    order = find_order(spec_change_order_id)
    if order["approval_status"] != "APPROVED":
        fail("ERR_SCO_INVALID_STATE", "Only an APPROVED order can be propagated.")
    current = order["propagation_status"]
    already = {
        "PREP_GUIDE": ("PREP_GUIDE_SYNCED", "FULLY_PROPAGATED"),
        "COUNT_SHEETS": ("COUNTS_SYNCED", "FULLY_PROPAGATED"),
    }[target]
    if current in already:
        fail("ERR_PROPAGATION_ALREADY_SYNCED",
             "The %s target of this order is already synced." % target)
    recipe = db.recipes.get(order["recipe_id"])
    if recipe is None:
        fail("ERR_RECIPE_NOT_FOUND", "The owning recipe no longer exists.")

    if target == "PREP_GUIDE":
        guide = prep_guide_of(recipe["id"])
        if guide is not None:
            guide["sync_state"] = "CURRENT"
            guide["revision_no"] = guide["revision_no"] + 1
            guide["batch_yield_base_units_snapshot"] = recipe["batch_yield_base_units"]
            guide["portions_per_batch_snapshot"] = recipe["portions_per_batch"]
            guide["component_count_snapshot"] = recipe["component_count"]
            guide["synced_spec_version"] = recipe["version"]
            touch(guide)
        order["propagation_status"] = ("FULLY_PROPAGATED" if current == "COUNTS_SYNCED"
                                      else "PREP_GUIDE_SYNCED")
    else:
        for line in sorted(db.count_lines.values(), key=order_key):
            if line["sync_state"] != "OUT_OF_DATE":
                continue
            review = db.period_reviews.get(line["period_review_id"])
            if review is None or review["status"] == "CLOSED":
                continue
            refresh_count_line(line, review["id"])
            line["sync_state"] = "CURRENT"
            line["synced_spec_version"] = recipe["version"]
            touch(line)
        order["propagation_status"] = ("FULLY_PROPAGATED"
                                      if current == "PREP_GUIDE_SYNCED"
                                      else "COUNTS_SYNCED")
    touch(order)
    return ok(serial.spec_change_order(order))


@bp.post("/culinary/spec-change-orders/<spec_change_order_id>/rollback")
def rollback_order(spec_change_order_id):
    authenticate(("CulinaryDirector",))
    order = find_order(spec_change_order_id)
    if order["approval_status"] != "APPROVED":
        fail("ERR_SCO_INVALID_STATE", "Only an APPROVED order can be rolled back.")
    recipe = db.recipes.get(order["recipe_id"])
    if recipe is None:
        fail("ERR_RECIPE_NOT_FOUND", "The owning recipe no longer exists.")

    # --- Restore the specification exactly.
    if order["change_type"] == "COMPONENT_QTY":
        target = db.recipe_components.get(order["target_component_id"])
        if target is not None:
            target["ep_quantity_base_units"] = order["pre_change_ep_quantity_base_units"]
            component_ingredient = db.ingredients.get(target["ingredient_id"])
            if component_ingredient is not None:
                target["ap_quantity_base_units"] = ap_from_ep(
                    target["ep_quantity_base_units"],
                    component_ingredient["net_yield_bps"])
            else:
                target["ap_quantity_base_units"] = target["ep_quantity_base_units"]
            touch(target)
    elif order["change_type"] == "COMPONENT_ADD":
        created_component = db.recipe_components.get(order["created_component_id"])
        if created_component is not None:
            created_component["status"] = "REMOVED"
            created_component["removed_at"] = db.now()
            touch(created_component)
    else:
        target = db.recipe_components.get(order["target_component_id"])
        if target is not None:
            target["status"] = "ACTIVE"
            target["removed_at"] = None
            touch(target)

    # --- Restore the two snapshotted figures, recompute the rest.
    recipe["batch_cost_micros"] = order["pre_change_batch_cost_micros"]
    recipe["allergen_mask"] = order["pre_change_allergen_mask"]
    apply_profile(recipe, keep_allergen=True)
    recipe["cost_state"] = "STALE"
    touch(recipe)
    ancestors = propagate_upward([recipe["id"]])

    order["approval_status"] = "ROLLED_BACK"
    order["propagation_status"] = "NOT_STARTED"
    touch(order)

    mark_prep_guide_out_of_date(recipe["id"])
    mark_count_lines_out_of_date(recipe["id"])
    stale_menu_items_of([recipe["id"]] + ancestors, source_recipe=recipe)
    return ok(serial.spec_change_order(order))
