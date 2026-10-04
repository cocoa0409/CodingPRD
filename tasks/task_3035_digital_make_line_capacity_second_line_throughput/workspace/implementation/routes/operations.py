"""Staffing deployments, suppression events, day close."""

from decimal import Decimal
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
    ERR_STALE_VERSION, ERR_INVALID_DEPLOYMENT, ERR_SEGREGATION_OF_DUTIES,
    ERR_DAY_NOT_CLOSABLE, ERR_MANUAL_SUPPRESSION_ONLY, ERR_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    new_resource, touch, parse_iso, iso_str, round_half_up,
    parse_pagination, paginate, require_fields, require_int, require_number,
    require_string, get_store_or_404, get_deployment_or_404,
    get_suppression_event_or_404, recompute_item_suppression,
)

bp = Blueprint("operations", __name__)

ALL_READ_ROLES = ("PlatformAdmin", "StoreManager", "GeneralManager", "LineWorker")


# ---------------------------------------------------------------------------
# Staffing deployments
# ---------------------------------------------------------------------------

def _validate_deployment_consistency(payload):
    digital_mix = require_number(payload, "predicted_digital_mix_pct")
    instore_mix = require_number(payload, "predicted_instore_mix_pct")
    headcount = require_int(payload, "headcount")
    shift_date = require_string(payload, "shift_date")
    if abs((digital_mix + instore_mix) - 1.0) > 1e-9:
        raise_error(ERR_INVALID_DEPLOYMENT, "Mix percentages must sum to 1")
    if headcount < 2:
        raise_error(ERR_INVALID_DEPLOYMENT, "headcount must be >= 2")
    # shift_date must not be in the past relative to the logical clock date
    from db import db as _db
    if shift_date < _db.clock.strftime("%Y-%m-%d"):
        raise_error(ERR_INVALID_DEPLOYMENT, "shift_date must not be in the past")
    return digital_mix, instore_mix, headcount, shift_date


@bp.post("/stores/<store_id>/staffing-deployments")
def create_deployment(store_id):
    require_roles("StoreManager")
    store = get_store_or_404(store_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, [
        "shift_date", "predicted_digital_mix_pct", "predicted_instore_mix_pct",
        "headcount", "expected_store_version",
    ])
    # OCC check (priority 4: before state and business rules)
    expected = payload["expected_store_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_store_version must be an integer")
    if expected != store["version"]:
        raise_error(ERR_STALE_VERSION,
                    f"Store version {store['version']} does not match expected {expected}")

    digital_mix, instore_mix, headcount, shift_date = _validate_deployment_consistency(payload)

    # Supersede existing DRAFT for same shift_date
    for d in db.deployments.values():
        if (d["store_id"] == store["id"] and d["shift_date"] == shift_date
                and d["status"] == "DRAFT"):
            d["status"] = "SUPERSEDED"
            touch(d)

    digital_headcount = round_half_up(Decimal(str(headcount)) * Decimal(str(digital_mix)))
    dep = new_resource()
    dep.update({
        "store_id": store["id"],
        "shift_date": shift_date,
        "predicted_digital_mix_pct": digital_mix,
        "predicted_instore_mix_pct": instore_mix,
        "headcount": headcount,
        "digital_headcount": digital_headcount,
        "instore_headcount": headcount - digital_headcount,
        "status": "DRAFT",
        "_publisher_id": None,
    })
    db.deployments[dep["id"]] = dep

    store["version"] += 1
    store["updated_at"] = dep["created_at"]

    return success_object(_public_deployment(dep), 201)


def _public_deployment(dep):
    return {k: v for k, v in dep.items() if not k.startswith("_")}


@bp.get("/stores/<store_id>/staffing-deployments")
def list_deployments_for_store(store_id):
    require_roles(*ALL_READ_ROLES)
    store = get_store_or_404(store_id)
    limit, offset = parse_pagination(request.args)
    items = [d for d in db.deployments.values() if d["store_id"] == store["id"]]
    shift_date = request.args.get("shift_date")
    status = request.args.get("status")
    if shift_date:
        items = [d for d in items if d["shift_date"] == shift_date]
    if status:
        items = [d for d in items if d["status"] == status]
    items, total = paginate(items, limit, offset)
    return success_list([_public_deployment(d) for d in items], total, limit, offset)


@bp.get("/staffing-deployments/<deployment_id>")
def get_deployment(deployment_id):
    require_roles(*ALL_READ_ROLES)
    dep = get_deployment_or_404(deployment_id)
    return success_object(_public_deployment(dep))


@bp.get("/staffing-deployments")
def list_deployments():
    require_roles(*ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.deployments.values())
    store_id = request.args.get("store_id")
    status = request.args.get("status")
    if store_id:
        items = [d for d in items if d["store_id"] == store_id]
    if status:
        items = [d for d in items if d["status"] == status]
    items, total = paginate(items, limit, offset)
    return success_list([_public_deployment(d) for d in items], total, limit, offset)


@bp.post("/stores/<store_id>/staffing-deployments/<deployment_id>/publish")
def publish_deployment(store_id, deployment_id):
    user_id, _ = require_roles("StoreManager")
    store = get_store_or_404(store_id)
    dep = get_deployment_or_404(deployment_id, store_id=store["id"])
    if dep["status"] in ("LOCKED", "SUPERSEDED"):
        raise_error(ERR_ALREADY_TERMINAL, f"Deployment is {dep['status']}")
    if dep["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"Deployment must be DRAFT, is {dep['status']}")
    # Consistency re-validated at publish
    if abs((dep["predicted_digital_mix_pct"] + dep["predicted_instore_mix_pct"]) - 1.0) > 1e-9:
        raise_error(ERR_INVALID_DEPLOYMENT, "Mix percentages must sum to 1")
    if dep["headcount"] < 2:
        raise_error(ERR_INVALID_DEPLOYMENT, "headcount must be >= 2")

    # Supersede prior PUBLISHED deployment for the same shift_date
    for d in db.deployments.values():
        if (d["store_id"] == store["id"] and d["shift_date"] == dep["shift_date"]
                and d["status"] == "PUBLISHED" and d["id"] != dep["id"]):
            d["status"] = "SUPERSEDED"
            touch(d)

    dep["status"] = "PUBLISHED"
    dep["_publisher_id"] = user_id
    touch(dep)
    return success_object(_public_deployment(dep), 200)


@bp.post("/stores/<store_id>/staffing-deployments/<deployment_id>/lock")
def lock_deployment(store_id, deployment_id):
    user_id, _ = require_roles("GeneralManager")
    store = get_store_or_404(store_id)
    dep = get_deployment_or_404(deployment_id, store_id=store["id"])
    if dep["status"] in ("LOCKED", "SUPERSEDED"):
        raise_error(ERR_ALREADY_TERMINAL, f"Deployment is {dep['status']}")
    if dep["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, f"Deployment must be PUBLISHED, is {dep['status']}")
    if dep.get("_publisher_id") == user_id:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "Lock must be performed by a different user than the publisher")
    dep["status"] = "LOCKED"
    touch(dep)
    return success_object(_public_deployment(dep), 200)


# ---------------------------------------------------------------------------
# Suppression events
# ---------------------------------------------------------------------------

@bp.get("/stores/<store_id>/suppression-events")
def list_suppression_for_store(store_id):
    require_roles(*ALL_READ_ROLES)
    store = get_store_or_404(store_id)
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.suppression_events.values() if e["store_id"] == store["id"]]
    items = _filter_suppression(items, request.args)
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/suppression-events/<event_id>")
def get_suppression_event(event_id):
    require_roles(*ALL_READ_ROLES)
    ev = get_suppression_event_or_404(event_id)
    return success_object(ev)


@bp.get("/suppression-events")
def list_suppression():
    require_roles(*ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.suppression_events.values())
    store_id = request.args.get("store_id")
    if store_id:
        items = [e for e in items if e["store_id"] == store_id]
    items = _filter_suppression(items, request.args)
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


def _filter_suppression(items, args):
    menu_item_id = args.get("menu_item_id")
    ingredient_id = args.get("ingredient_id")
    status = args.get("status")
    if menu_item_id:
        items = [e for e in items if e["menu_item_id"] == menu_item_id]
    if ingredient_id:
        items = [e for e in items if e["ingredient_id"] == ingredient_id]
    if status:
        items = [e for e in items if e["status"] == status]
    return items


@bp.post("/stores/<store_id>/suppression-events/<event_id>/resolve")
def resolve_suppression(store_id, event_id):
    require_roles("StoreManager")
    store = get_store_or_404(store_id)
    ev = get_suppression_event_or_404(event_id, store_id=store["id"])
    if ev["status"] == "RESOLVED":
        raise_error(ERR_ALREADY_TERMINAL, "Suppression event already RESOLVED")
    if ev["cause"] != "MANUAL":
        raise_error(ERR_MANUAL_SUPPRESSION_ONLY,
                    "Only MANUAL-cause suppression events may be manually resolved")
    ev["status"] = "RESOLVED"
    touch(ev)
    item = db.menu_items.get(ev["menu_item_id"])
    if item is not None:
        recompute_item_suppression(item)
    return success_object(ev, 200)


# ---------------------------------------------------------------------------
# Day close
# ---------------------------------------------------------------------------

@bp.post("/stores/<store_id>/day-close")
def day_close(store_id):
    require_roles("GeneralManager")
    store = get_store_or_404(store_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["expected_store_version"])
    expected = payload["expected_store_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_store_version must be an integer")
    if expected != store["version"]:
        raise_error(ERR_STALE_VERSION,
                    f"Store version {store['version']} does not match expected {expected}")

    # Precondition: all windows SETTLED; no live orders.
    live_orders = [
        o for o in db.orders.values()
        if o["store_id"] == store["id"]
        and o["fulfillment_status"] in ("PLACED", "ACCEPTED", "IN_PRODUCTION")
    ]
    unsettled = [
        w for w in db.production_windows.values()
        if w["store_id"] == store["id"] and w["status"] in ("OPEN", "CUTOFF")
    ]
    # CUTOFF windows can be settled by the close itself; OPEN windows cannot.
    open_windows = [w for w in unsettled if w["status"] == "OPEN"]
    if open_windows or live_orders:
        raise_error(ERR_DAY_NOT_CLOSABLE,
                    "Day close blocked: unsettled production windows or live orders remain")

    # Settle remaining CUTOFF windows.
    for w in unsettled:
        w["status"] = "SETTLED"
        touch(w)

    day_orders = [o for o in db.orders.values() if o["store_id"] == store["id"]]
    orders_accepted = len(day_orders)  # all persisted orders reached ACCEPTED
    orders_completed = sum(1 for o in day_orders if o["fulfillment_status"] == "PICKED_UP")
    digital_net = sum(
        o["net_revenue_cents"] for o in day_orders
        if o["channel"] in ("FIRST_PARTY_DIGITAL", "MARKETPLACE")
    )
    instore_net = sum(
        o["net_revenue_cents"] for o in day_orders if o["channel"] == "IN_STORE"
    )

    close = new_resource()
    close.update({
        "store_id": store["id"],
        "business_day": store["current_business_day"],
        "orders_accepted": orders_accepted,
        "orders_completed": orders_completed,
        "digital_net_revenue_cents": digital_net,
        "instore_net_revenue_cents": instore_net,
        "food_cost_variance_bps": store["food_cost_variance_bps"],
        "status": "CLOSED",
    })
    db.day_closes[close["id"]] = close

    # Advance business day and bump version
    next_day = (parse_iso(store["current_business_day"] + "T00:00:00Z") + timedelta(days=1)).strftime("%Y-%m-%d")
    store["current_business_day"] = next_day
    store["version"] += 1
    store["updated_at"] = close["created_at"]

    return success_object(close, 201)


@bp.get("/stores/<store_id>/day-closes")
def list_day_closes_for_store(store_id):
    require_roles("PlatformAdmin", "StoreManager", "GeneralManager")
    store = get_store_or_404(store_id)
    limit, offset = parse_pagination(request.args)
    items = [c for c in db.day_closes.values() if c["store_id"] == store["id"]]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/day-closes")
def list_day_closes():
    require_roles("PlatformAdmin", "StoreManager", "GeneralManager")
    limit, offset = parse_pagination(request.args)
    items = list(db.day_closes.values())
    store_id = request.args.get("store_id")
    if store_id:
        items = [c for c in items if c["store_id"] == store_id]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/day-closes/<day_close_id>")
def get_day_close(day_close_id):
    require_roles("PlatformAdmin", "StoreManager", "GeneralManager")
    c = db.day_closes.get(day_close_id)
    if c is None:
        raise_error(ERR_NOT_FOUND, f"Day close {day_close_id} not found")
    return success_object(c)
