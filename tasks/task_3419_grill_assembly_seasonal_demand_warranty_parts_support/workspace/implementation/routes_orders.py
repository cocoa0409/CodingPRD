"""PartsOrder placement (synchronous supersession resolution) and lifecycle.
PRD §3.8, calc_parts_supersession_resolution."""

from flask import Blueprint, request

import clock
import derive
from auth import authenticate, require_role
from constants import FULFILLMENT_TYPES
from errors import api_error, not_found, validation
from serialize import parts_order_out
from store import db, new_entity, next_seq, touch
from util import as_int, get_body, ok, ok_list, paginate, req_enum, require

bp = Blueprint("parts_orders", __name__, url_prefix="/grillops")

ROLES = ("ServiceAgent", "PlannerAdmin")

ORDER_VALID_FROM = {
    "SHIP": ("ALLOCATED",),
    "DELIVER": ("SHIPPED",),
    "CANCEL": ("REQUESTED", "BACKORDERED", "ALLOCATED"),
}


def _resolve_and_stock(order, requested, quantity):
    """calc_parts_supersession_resolution: ordered walk along the requested
    part's supersession chain. Sets resolved_part_id / status / total_cost and
    decrements stock on allocation."""
    candidate = requested
    while True:
        if candidate["status"] in ("AVAILABLE", "LOW_STOCK") and candidate["stock_quantity"] >= quantity:
            order["resolved_part_id"] = candidate["id"]
            order["total_cost_cents"] = candidate["unit_cost_cents"] * quantity
            candidate["stock_quantity"] -= quantity
            derive.derive_part_status(candidate)
            touch(candidate)
            order["status"] = "ALLOCATED"
            return
        if candidate["status"] == "OBSOLETE":
            raise api_error("ERR_PART_UNAVAILABLE", "part is OBSOLETE")
        successor = None
        for other in db.parts.values():
            if (
                other["supersession_chain_id"] == candidate["supersession_chain_id"]
                and other["chain_position"] == candidate["chain_position"] + 1
            ):
                successor = other
                break
        if successor is not None:
            candidate = successor
            continue
        # chain exhausted
        if requested["status"] == "EXHAUSTED":
            order["resolved_part_id"] = requested["id"]
            order["total_cost_cents"] = requested["unit_cost_cents"] * quantity
            order["status"] = "BACKORDERED"
            return
        raise api_error("ERR_PART_UNAVAILABLE", "requested part is superseded with no fulfiller downstream")


@bp.post("/parts-orders")
def create_parts_order():
    _, role = authenticate()
    require_role(role, ("ServiceAgent",))
    data = get_body()
    # rung 3: body-carried references, left to right in input order
    part_id = require(data, "part_id")
    part = db.parts.get(part_id)
    if part is None:
        raise not_found("PART")
    sale_id = require(data, "sale_id")
    sale = db.sales.get(sale_id)
    if sale is None:
        raise not_found("SALE")
    # rung 6: body
    quantity = as_int(require(data, "quantity"), "quantity")
    if quantity < 1:
        raise validation("quantity must be >= 1")
    fulfillment_type = req_enum(data, "fulfillment_type", FULFILLMENT_TYPES)
    claim_ref = data.get("warranty_claim_id")  # informational, NOT an FK
    if claim_ref is not None and not isinstance(claim_ref, str):
        raise validation("warranty_claim_id must be a string")
    free_of_charge = fulfillment_type in ("WARRANTY", "GOODWILL")
    model = db.models.get(sale["model_id"])
    # rung 7: part availability (OBSOLETE fails before the walk) then fitment
    if part["status"] == "OBSOLETE":
        raise api_error("ERR_PART_UNAVAILABLE", "part is OBSOLETE")
    if model is None or model["model_code"] not in part["compatible_model_codes"]:
        raise api_error("ERR_PART_INCOMPATIBLE", "part does not fit the sale's model")
    # rung 8: free orders respect the model's parts-support obligation window
    if free_of_charge and model["support_obligation_until"] is not None:
        if clock.now() > clock.parse_iso(model["support_obligation_until"]):
            raise api_error("ERR_PARTS_OBLIGATION_EXPIRED", "the model's parts-support obligation has expired")
    order = new_entity({
        "part_id": part["id"],
        "sale_id": sale["id"],
        "warranty_claim_id": claim_ref,
        "fulfillment_type": fulfillment_type,
        "quantity": quantity,
        "resolved_part_id": None,
        "free_of_charge": free_of_charge,
        "total_cost_cents": None,
        "status": "REQUESTED",
        "seq_no": next_seq(),
    })
    db.parts_orders[order["id"]] = order
    # resolution is synchronous within the create (REQUESTED -> ALLOCATED |
    # BACKORDERED inside this request)
    _resolve_and_stock(order, part, quantity)
    touch(order)
    return ok(parts_order_out(order), status=201)


@bp.get("/parts-orders/<order_id>")
def get_parts_order(order_id):
    _, role = authenticate()
    require_role(role, ROLES)
    order = db.parts_orders.get(order_id)
    if order is None:
        raise not_found("PARTS_ORDER")
    return ok(parts_order_out(order))


@bp.get("/parts-orders")
def list_parts_orders():
    _, role = authenticate()
    require_role(role, ROLES)
    items = list(db.parts_orders.values())
    for field in ("part_id", "sale_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            items = [o for o in items if o.get(field) == raw]
    page, total, limit, offset = paginate(items)
    return ok_list([parts_order_out(o) for o in page], total, limit, offset)


@bp.post("/parts-orders/<order_id>/transition")
def transition_parts_order(order_id):
    _, role = authenticate()
    require_role(role, ("ServiceAgent",))
    order = db.parts_orders.get(order_id)
    if order is None:
        raise not_found("PARTS_ORDER")
    data = get_body()
    action = require(data, "action")
    if action not in ORDER_VALID_FROM:
        raise validation("action must be one of SHIP, DELIVER, CANCEL")
    # rung 5: valid-from state
    if order["status"] not in ORDER_VALID_FROM[action]:
        raise api_error(
            "ERR_INVALID_STATE",
            "action %s is not available from status %s" % (action, order["status"]),
        )
    if action == "SHIP":
        order["status"] = "SHIPPED"
    elif action == "DELIVER":
        order["status"] = "DELIVERED"
    elif action == "CANCEL":
        was_allocated = order["status"] == "ALLOCATED"
        order["status"] = "CANCELLED"
        if was_allocated:
            # compensating: credit the resolved part's stock back
            part = db.parts.get(order["resolved_part_id"])
            if part is not None:
                part["stock_quantity"] += order["quantity"]
                derive.derive_part_status(part)
                touch(part)
    touch(order)
    return ok(parts_order_out(order))
