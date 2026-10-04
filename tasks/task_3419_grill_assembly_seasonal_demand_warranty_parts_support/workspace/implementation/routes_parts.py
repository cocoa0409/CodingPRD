"""PartSku catalog: create, read, and stock/supersession lifecycle (PRD §3.8)."""

from flask import Blueprint

import derive
from auth import authenticate, require_role
from constants import CLAIM_COMPONENTS
from errors import api_error, not_found, validation
from serialize import part_out
from store import db, new_entity, touch
from util import as_int, as_list, get_body, ok, opt_int, req_int, req_str, require

bp = Blueprint("parts", __name__, url_prefix="/grillops")

VALID_FROM = {
    "RESTOCK": ("LOW_STOCK", "EXHAUSTED"),
    "MARK_EXHAUSTED": ("AVAILABLE", "LOW_STOCK"),
    "SUPERSEDE": ("AVAILABLE", "LOW_STOCK", "EXHAUSTED"),
    "MARK_OBSOLETE": ("SUPERSEDED",),
}


@bp.post("/parts")
def create_part():
    _, role = authenticate()
    require_role(role, ("PlannerAdmin",))
    data = get_body()
    part_number = req_str(data, "part_number")
    component = req_str(data, "component")
    if component not in CLAIM_COMPONENTS:
        raise validation("component must be one of BURNER, GRATE, ELECTRONICS, OTHER")
    compatible = as_list(require(data, "compatible_model_codes"), "compatible_model_codes")
    if not compatible:
        raise validation("compatible_model_codes must be non-empty")
    for code in compatible:
        if not isinstance(code, str) or not code:
            raise validation("compatible_model_codes entries must be non-empty strings")
    chain_id = req_str(data, "supersession_chain_id")
    chain_position = req_int(data, "chain_position")
    unit_cost_cents = req_int(data, "unit_cost_cents")
    if unit_cost_cents < 0:
        raise validation("unit_cost_cents must be >= 0")
    stock_quantity = opt_int(data, "stock_quantity", 0)
    if stock_quantity < 0:
        raise validation("stock_quantity must be >= 0")
    # rung 9 uniqueness: chain_position unique within the chain (ERR_VALIDATION);
    # part_number unique (no dedicated code -> ERR_VALIDATION)
    for other in db.parts.values():
        if other["supersession_chain_id"] == chain_id and other["chain_position"] == chain_position:
            raise validation("chain_position must be unique within a supersession chain")
    for other in db.parts.values():
        if other["part_number"] == part_number:
            raise validation("part_number must be unique")
    part = new_entity({
        "part_number": part_number,
        "component": component,
        "compatible_model_codes": compatible,
        "supersession_chain_id": chain_id,
        "chain_position": chain_position,
        "unit_cost_cents": unit_cost_cents,
        "stock_quantity": stock_quantity,
        # stock level derives status automatically, including at creation
        "status": derive.part_status_for(stock_quantity),
    })
    db.parts[part["id"]] = part
    return ok(part_out(part), status=201)


@bp.get("/parts/<part_id>")
def get_part(part_id):
    _, role = authenticate()
    require_role(role, ("PlannerAdmin", "ServiceAgent"))
    part = db.parts.get(part_id)
    if part is None:
        raise not_found("PART")
    return ok(part_out(part))


def _fill_backorders(part):
    """RESTOCK drains the backorder queue in created_at ASC order, ties broken
    by seq_no ASC (never id), until the stock or the backorders run out."""
    queue = [
        o for o in db.parts_orders.values()
        if o["status"] == "BACKORDERED" and o["resolved_part_id"] == part["id"]
    ]
    queue.sort(key=lambda o: (o["created_at"], o["seq_no"]))
    for order in queue:
        if part["stock_quantity"] >= order["quantity"]:
            part["stock_quantity"] -= order["quantity"]
            order["status"] = "ALLOCATED"
            touch(order)
        else:
            break  # FIFO: stop at the first order the stock cannot fill


@bp.post("/parts/<part_id>/transition")
def transition_part(part_id):
    _, role = authenticate()
    require_role(role, ("PlannerAdmin", "ServiceAgent"))
    part = db.parts.get(part_id)
    if part is None:
        raise not_found("PART")
    data = get_body()
    action = require(data, "action")
    if action not in VALID_FROM:
        raise validation("action must be one of RESTOCK, MARK_EXHAUSTED, SUPERSEDE, MARK_OBSOLETE")
    # rung 5: valid-from state
    if part["status"] not in VALID_FROM[action]:
        raise api_error(
            "ERR_INVALID_STATE",
            "action %s is not available from status %s" % (action, part["status"]),
        )
    if action == "RESTOCK":
        quantity = as_int(require(data, "quantity"), "quantity")
        if quantity < 1:
            raise validation("quantity must be >= 1")
        part["stock_quantity"] += quantity
        _fill_backorders(part)
        # lands AVAILABLE above the low-stock threshold, LOW_STOCK otherwise
        derive.derive_part_status(part)
    elif action == "MARK_EXHAUSTED":
        part["stock_quantity"] = 0
        part["status"] = "EXHAUSTED"
    elif action == "SUPERSEDE":
        successor_id = require(data, "successor_part_id")
        successor = db.parts.get(successor_id)
        if (
            successor is None
            or successor["supersession_chain_id"] != part["supersession_chain_id"]
            or successor["chain_position"] <= part["chain_position"]
        ):
            raise validation("successor must exist, share the supersession_chain_id, and hold a strictly higher chain_position")
        part["status"] = "SUPERSEDED"
    elif action == "MARK_OBSOLETE":
        part["status"] = "OBSOLETE"
    touch(part)
    return ok(part_out(part))
