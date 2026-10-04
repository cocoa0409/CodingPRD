"""Order routes: place, serve, cancel; modifier pricing; surge pacing."""

from flask import Blueprint, request

import db
import services.calculations as calc
import services.domain as domain
from errors import (
    ERR_INSUFFICIENT_INVENTORY,
    ERR_ORDER_INVALID_STATE,
    conflict,
    forbidden,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    get_json_body,
    paginate,
    req_field,
    req_list,
    req_string,
    touch,
)

bp = Blueprint("orders", __name__)


def _order_footprint(lines):
    """Compute (required_patties, required_buns, required_produce) per
    order_inventory_reservation. Buns: exactly one per unit sold."""
    patties = 0
    buns = 0
    produce = 0
    for line in lines:
        item = db.menu_items.get(line["menu_item_id"])
        qty = line["qty"]
        extra = sum(1 for c in line["modifier_codes"] if c == "EXTRA_PATTY")
        patties += qty * (1 + extra) * item["patty_count"]
        buns += qty
        produce += qty * item["produce_units"]
    return patties, buns, produce


def _validate_lines(lines):
    """Shape + FK existence for order lines. Returns normalized line dicts."""
    if not isinstance(lines, list):
        raise invalid_request("lines must be an array")
    out = []
    for line in lines:
        if not isinstance(line, dict):
            raise invalid_request("each line must be an object")
        mid = line.get("menu_item_id")
        if not isinstance(mid, str):
            raise invalid_request("line.menu_item_id must be a string")
        qty = line.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise invalid_request("line.qty must be a positive integer")
        mods = line.get("modifier_codes", [])
        if not isinstance(mods, list) or not all(isinstance(c, str) for c in mods):
            raise invalid_request("line.modifier_codes must be an array of strings")
        for c in mods:
            if c not in calc.MODIFIER_CODES:
                raise invalid_request("Unknown modifier code: %s" % c)
        # Body FK existence (tier 5).
        domain.get_menu_item(mid)
        out.append({"menu_item_id": mid, "qty": qty, "modifier_codes": list(mods)})
    return out


@bp.route("/stores/<sid>/orders", methods=["POST"])
def place_order(sid):
    # StoreManager acts as an associate at their own store for register operations.
    user_id, _ = require_roles("Associate", "StoreManager")
    # Path existence (tier 4).
    store = domain.get_store(sid)
    body = get_json_body()
    placed_by = req_string(body, "placed_by_associate_id")
    # Identity/ownership (tier 3): caller must be the associate placing the order.
    if user_id != placed_by:
        raise forbidden("Associate may only place orders as themselves")
    # Body FK existence (tier 5): the placing associate must exist.
    domain.get_associate(placed_by)
    lines = _validate_lines(req_field(body, "lines"))
    # Modifier pricing (pinned order: per-line round, then sum).
    base_total = 0
    modifier_charge = 0
    for line in lines:
        item = db.menu_items[line["menu_item_id"]]
        base_total += item["base_price_cents"] * line["qty"]
        modifier_charge += calc.line_modifier_cents(line["qty"], line["modifier_codes"])
    # All-or-nothing inventory waterfall (tier 19).
    req_patties, req_buns, req_produce = _order_footprint(lines)
    inv = db.inventory_for(store["id"])
    if (
        inv["patties"] < req_patties
        or inv["buns"] < req_buns
        or inv["produce_units"] < req_produce
    ):
        raise unprocessable(ERR_INSUFFICIENT_INVENTORY, "Store on-hand inventory cannot cover the order")
    # Surge pacing / queue mechanics.
    mode_now, pacing, queue_position = calc.surge_pacing(store)
    if store["opening_mode"] == "OPENING_SURGE" and mode_now == "NORMAL":
        # Window elapsed: auto-revert persisted.
        store["opening_mode"] = "NORMAL"
        store["surge_start_date"] = None
        store["surge_end_date"] = None
    # Commit reservation. The all-or-nothing check covers all three
    # commodities; the placement debit consumes patties.
    inv["patties"] -= req_patties
    o = base_entity()
    o.update({
        "store_id": store["id"],
        "placed_by_associate_id": placed_by,
        "lines": lines,
        "base_total_cents": base_total,
        "modifier_charge_cents": modifier_charge,
        "total_price_cents": base_total + modifier_charge,
        "patties_reserved": req_patties,
        "queue_position": queue_position,
        "surge_pacing_minutes": pacing,
        "status": "PLACED",
    })
    db.orders[o["id"]] = o
    return success_object(domain.ser_order(o), 201)


@bp.route("/stores/<sid>/orders", methods=["GET"])
def list_store_orders(sid):
    require_roles("Associate", "StoreManager")
    store = domain.get_store(sid)
    items = [o for o in db.orders.values() if o["store_id"] == store["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_order(o) for o in page], limit, offset, total)


@bp.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    require_roles("Associate", "StoreManager")
    return success_object(domain.ser_order(domain.get_order(oid)))


@bp.route("/orders", methods=["GET"])
def list_orders():
    require_roles("StoreManager", "HRDirector")
    items = list(db.orders.values())
    aid = request.args.get("placed_by_associate_id")
    if aid is not None:
        items = [o for o in items if o["placed_by_associate_id"] == aid]
    sid = request.args.get("store_id")
    if sid is not None:
        items = [o for o in items if o["store_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_order(o) for o in page], limit, offset, total)


def _require_store_associate(user_id, order):
    """Associate identity: active associate whose home store is the order's store."""
    assoc = db.associates.get(user_id)
    if assoc is None or assoc["home_store_id"] != order["store_id"] or not assoc.get("active", True):
        raise forbidden("Only an active associate of the order's store may act on it")


@bp.route("/orders/<oid>/serve", methods=["POST"])
def serve_order(oid):
    user_id, _ = require_roles("Associate", "StoreManager")
    order = domain.get_order(oid)
    _require_store_associate(user_id, order)
    if order["status"] != "PLACED":
        raise conflict(ERR_ORDER_INVALID_STATE, "Order must be PLACED to serve")
    order["status"] = "SERVED"
    order["queue_position"] = None
    touch(order)
    return success_object(domain.ser_order(order))


@bp.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, _ = require_roles("Associate", "StoreManager")
    order = domain.get_order(oid)
    _require_store_associate(user_id, order)
    if order["status"] != "PLACED":
        raise conflict(ERR_ORDER_INVALID_STATE, "Order must be PLACED to cancel")
    # Compensating action: re-credit the reserved patties.
    req_patties, req_buns, req_produce = _order_footprint(order["lines"])
    inv = db.inventory_for(order["store_id"])
    inv["patties"] += req_patties
    order["status"] = "CANCELLED"
    order["queue_position"] = None
    touch(order)
    return success_object(domain.ser_order(order))
