"""Batches, menu items, recipe components, production windows, waste events."""

from decimal import Decimal
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_WINDOW_OVERLAP,
    ERR_WASTE_EXCEEDS_BATCH, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    new_resource, touch, parse_iso, iso_str, round_half_up,
    parse_pagination, paginate, require_fields, require_int, require_string,
    get_store_or_404, get_ingredient_or_404, get_batch_or_404,
    get_menu_item_or_404, evaluate_shortage, update_food_cost_variance,
)

bp = Blueprint("kitchen", __name__)

ALL_READ_ROLES = ("PlatformAdmin", "StoreManager", "GeneralManager", "LineWorker")


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

@bp.post("/ingredients/<ingredient_id>/batches")
def cook_batch(ingredient_id):
    require_roles("LineWorker", "StoreManager")
    ingredient = get_ingredient_or_404(ingredient_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["store_id", "cooked_at", "grams_cooked"])
    store = get_store_or_404(payload["store_id"])
    cooked_at = parse_iso(payload["cooked_at"])
    grams = require_int(payload, "grams_cooked", minimum=1)

    batch = new_resource()
    discard_at = cooked_at + timedelta(minutes=ingredient["hold_time_minutes"])
    batch.update({
        "ingredient_id": ingredient["id"],
        "store_id": store["id"],
        "cooked_at": iso_str(cooked_at),
        "grams_cooked": grams,
        "grams_remaining": grams,
        "discard_at": iso_str(discard_at),
        "discarded_grams": 0,
        "status": "ACTIVE",
    })
    db.batches[batch["id"]] = batch

    ingredient["on_hand_grams"] += grams
    touch(ingredient)
    # Recovery: crossing back above 0.5*par resolves shortage events.
    evaluate_shortage(ingredient)
    return success_object(batch, 201)


@bp.get("/ingredients/<ingredient_id>/batches")
def list_batches_for_ingredient(ingredient_id):
    require_roles(*ALL_READ_ROLES)
    ingredient = get_ingredient_or_404(ingredient_id)
    limit, offset = parse_pagination(request.args)
    items = [b for b in db.batches.values() if b["ingredient_id"] == ingredient["id"]]
    status = request.args.get("status")
    if status:
        items = [b for b in items if b["status"] == status]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/batches/<batch_id>")
def get_batch(batch_id):
    require_roles(*ALL_READ_ROLES)
    batch = get_batch_or_404(batch_id)
    return success_object(batch)


@bp.get("/batches")
def list_batches():
    require_roles(*ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.batches.values())
    ingredient_id = request.args.get("ingredient_id")
    store_id = request.args.get("store_id")
    status = request.args.get("status")
    if ingredient_id:
        items = [b for b in items if b["ingredient_id"] == ingredient_id]
    if store_id:
        items = [b for b in items if b["store_id"] == store_id]
    if status:
        items = [b for b in items if b["status"] == status]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


# ---------------------------------------------------------------------------
# Menu items
# ---------------------------------------------------------------------------

@bp.post("/stores/<store_id>/menu-items")
def create_menu_item(store_id):
    require_roles("StoreManager")
    store = get_store_or_404(store_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["item_code", "display_name", "base_price_cents"])
    eligible = payload.get("is_digital_eligible", True)
    if not isinstance(eligible, bool):
        raise_error(ERR_INVALID_REQUEST, "is_digital_eligible must be a boolean")
    item = new_resource()
    item.update({
        "store_id": store["id"],
        "item_code": require_string(payload, "item_code"),
        "display_name": require_string(payload, "display_name"),
        "base_price_cents": require_int(payload, "base_price_cents", minimum=0),
        "is_digital_eligible": eligible,
        "theoretical_cost_cents": 0,
        "suppression_state": "SELLABLE",
    })
    db.menu_items[item["id"]] = item
    return success_object(item, 201)


@bp.get("/stores/<store_id>/menu-items")
def list_menu_items_for_store(store_id):
    require_roles(*ALL_READ_ROLES)
    store = get_store_or_404(store_id)
    limit, offset = parse_pagination(request.args)
    items = [m for m in db.menu_items.values() if m["store_id"] == store["id"]]
    suppression_state = request.args.get("suppression_state")
    if suppression_state:
        items = [m for m in items if m["suppression_state"] == suppression_state]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/menu-items/<menu_item_id>")
def get_menu_item(menu_item_id):
    require_roles(*ALL_READ_ROLES)
    item = get_menu_item_or_404(menu_item_id)
    return success_object(item)


@bp.get("/menu-items")
def list_menu_items():
    require_roles(*ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.menu_items.values())
    store_id = request.args.get("store_id")
    suppression_state = request.args.get("suppression_state")
    if store_id:
        items = [m for m in items if m["store_id"] == store_id]
    if suppression_state:
        items = [m for m in items if m["suppression_state"] == suppression_state]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


# ---------------------------------------------------------------------------
# Recipe components
# ---------------------------------------------------------------------------

def _recompute_theoretical_cost(item):
    total = Decimal("0")
    for rc in db.recipe_components.values():
        if rc["menu_item_id"] == item["id"]:
            ing = db.ingredients[rc["ingredient_id"]]
            total += Decimal(str(rc["standard_grams"])) * Decimal(str(ing["unit_cost_cents_per_gram"]))
    item["theoretical_cost_cents"] = round_half_up(total)
    touch(item)


@bp.post("/menu-items/<menu_item_id>/recipe-components")
def add_recipe_component(menu_item_id):
    require_roles("StoreManager")
    item = get_menu_item_or_404(menu_item_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["ingredient_id", "standard_grams"])
    ingredient = get_ingredient_or_404(payload["ingredient_id"])
    grams = require_int(payload, "standard_grams", minimum=1)
    rc = new_resource()
    rc.update({
        "menu_item_id": item["id"],
        "ingredient_id": ingredient["id"],
        "standard_grams": grams,
    })
    db.recipe_components[rc["id"]] = rc
    _recompute_theoretical_cost(item)
    return success_object(rc, 201)


@bp.get("/menu-items/<menu_item_id>/recipe-components")
def list_components_for_item(menu_item_id):
    require_roles(*ALL_READ_ROLES)
    item = get_menu_item_or_404(menu_item_id)
    limit, offset = parse_pagination(request.args)
    items = [rc for rc in db.recipe_components.values() if rc["menu_item_id"] == item["id"]]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/recipe-components")
def list_components():
    require_roles(*ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.recipe_components.values())
    menu_item_id = request.args.get("menu_item_id")
    ingredient_id = request.args.get("ingredient_id")
    if menu_item_id:
        items = [rc for rc in items if rc["menu_item_id"] == menu_item_id]
    if ingredient_id:
        items = [rc for rc in items if rc["ingredient_id"] == ingredient_id]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/recipe-components/<component_id>")
def get_component(component_id):
    require_roles(*ALL_READ_ROLES)
    from errors import ERR_NOT_FOUND
    rc = db.recipe_components.get(component_id)
    if rc is None:
        raise_error(ERR_NOT_FOUND, f"Recipe component {component_id} not found")
    return success_object(rc)


# ---------------------------------------------------------------------------
# Production windows
# ---------------------------------------------------------------------------

@bp.post("/stores/<store_id>/production-windows")
def create_window(store_id):
    require_roles("StoreManager", "PlatformAdmin")
    store = get_store_or_404(store_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["interval_start", "interval_end"])
    start = parse_iso(payload["interval_start"])
    end = parse_iso(payload["interval_end"])
    expected_end = start + timedelta(minutes=store["pacing_interval_minutes"])
    if end != expected_end:
        raise_error(ERR_INVALID_REQUEST,
                    "interval_end must equal interval_start + pacing_interval_minutes")

    # Overlap check: half-open [start, end); adjacency permitted.
    for w in db.production_windows.values():
        if w["store_id"] != store["id"]:
            continue
        w_start = parse_iso(w["interval_start"])
        w_end = parse_iso(w["interval_end"])
        if start < w_end and w_start < end:
            raise_error(ERR_WINDOW_OVERLAP,
                        "Production window interval overlaps an existing window")

    w = new_resource()
    w.update({
        "store_id": store["id"],
        "interval_start": iso_str(start),
        "interval_end": iso_str(end),
        "digital_capacity": store["digital_line_capacity_per_interval"],
        "digital_committed": 0,
        "digital_completed": 0,
        "instore_committed": 0,
        "status": "OPEN",
    })
    # If the window's start is already at/past the logical clock, it is immediately CUTOFF.
    if start <= db.clock:
        w["status"] = "CUTOFF"
    db.production_windows[w["id"]] = w
    return success_object(w, 201)


@bp.get("/stores/<store_id>/production-windows")
def list_windows_for_store(store_id):
    require_roles(*ALL_READ_ROLES)
    store = get_store_or_404(store_id)
    limit, offset = parse_pagination(request.args)
    items = [w for w in db.production_windows.values() if w["store_id"] == store["id"]]
    status = request.args.get("status")
    if status:
        items = [w for w in items if w["status"] == status]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/production-windows/<window_id>")
def get_window(window_id):
    require_roles(*ALL_READ_ROLES)
    from errors import ERR_NOT_FOUND
    w = db.production_windows.get(window_id)
    if w is None:
        raise_error(ERR_NOT_FOUND, f"Production window {window_id} not found")
    return success_object(w)


@bp.get("/production-windows")
def list_windows():
    require_roles(*ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.production_windows.values())
    store_id = request.args.get("store_id")
    status = request.args.get("status")
    if store_id:
        items = [w for w in items if w["store_id"] == store_id]
    if status:
        items = [w for w in items if w["status"] == status]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


# ---------------------------------------------------------------------------
# Waste events
# ---------------------------------------------------------------------------

@bp.post("/stores/<store_id>/waste-events")
def record_waste(store_id):
    require_roles("LineWorker", "StoreManager")
    store = get_store_or_404(store_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["ingredient_batch_id", "grams", "reason"])
    batch = get_batch_or_404(payload["ingredient_batch_id"])
    grams = require_int(payload, "grams", minimum=1)
    reason = payload["reason"]
    if reason not in ("HOLD_TIME_EXPIRED", "CONTAMINATION", "OVERPRODUCTION"):
        raise_error(ERR_INVALID_REQUEST, "reason must be HOLD_TIME_EXPIRED, CONTAMINATION, or OVERPRODUCTION")

    if grams > batch["grams_remaining"]:
        raise_error(ERR_WASTE_EXCEEDS_BATCH, "Waste grams exceed batch grams_remaining")
    if batch["status"] in ("DEPLETED", "EXPIRED", "WASTED"):
        raise_error(ERR_ALREADY_TERMINAL, f"Batch is {batch['status']}")
    if batch["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Batch must be ACTIVE")

    ingredient = db.ingredients[batch["ingredient_id"]]
    cost = round_half_up(Decimal(str(grams)) * Decimal(str(ingredient["unit_cost_cents_per_gram"])))

    ev = new_resource()
    ev.update({
        "store_id": store["id"],
        "ingredient_batch_id": batch["id"],
        "grams": grams,
        "reason": reason,
        "cost_cents": cost,
    })
    db.waste_events[ev["id"]] = ev

    batch["grams_remaining"] -= grams
    batch["discarded_grams"] += grams
    full_waste = batch["grams_remaining"] == 0
    if full_waste and reason in ("CONTAMINATION", "OVERPRODUCTION"):
        batch["status"] = "WASTED"
    touch(batch)

    ingredient["on_hand_grams"] -= grams
    touch(ingredient)
    store["actual_food_cost_cents"] += cost
    touch(store)
    update_food_cost_variance(store)
    evaluate_shortage(ingredient)

    return success_object(ev, 201)


@bp.get("/stores/<store_id>/waste-events")
def list_waste_for_store(store_id):
    require_roles("PlatformAdmin", "StoreManager", "GeneralManager")
    store = get_store_or_404(store_id)
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.waste_events.values() if e["store_id"] == store["id"]]
    batch_id = request.args.get("ingredient_batch_id")
    if batch_id:
        items = [e for e in items if e["ingredient_batch_id"] == batch_id]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/waste-events")
def list_waste():
    require_roles("PlatformAdmin", "StoreManager", "GeneralManager")
    limit, offset = parse_pagination(request.args)
    items = list(db.waste_events.values())
    store_id = request.args.get("store_id")
    batch_id = request.args.get("ingredient_batch_id")
    if store_id:
        items = [e for e in items if e["store_id"] == store_id]
    if batch_id:
        items = [e for e in items if e["ingredient_batch_id"] == batch_id]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/waste-events/<waste_event_id>")
def get_waste(waste_event_id):
    require_roles("PlatformAdmin", "StoreManager", "GeneralManager")
    from errors import ERR_NOT_FOUND
    ev = db.waste_events.get(waste_event_id)
    if ev is None:
        raise_error(ERR_NOT_FOUND, f"Waste event {waste_event_id} not found")
    return success_object(ev)
