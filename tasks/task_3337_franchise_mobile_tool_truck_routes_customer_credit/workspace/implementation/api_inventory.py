"""Truck inventory positions."""

from flask import Blueprint

import auth
import envelope
import lookup
import recompute
import store
from errors import fail

bp = Blueprint("inventory", __name__, url_prefix="/retail")

POSITION_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer",
                  "RouteSalesRep")


@bp.post("/routes/<route_id>/inventory-positions")
def write_position(route_id):
    user_id, role = auth.require("FranchiseOwner", "FranchiseManager")
    route = lookup.route(route_id)
    auth.ensure_owned(user_id, role, route.get("franchisee_id"))
    payload = envelope.body()
    product_id = envelope.as_str(payload, "product_id")
    on_hand_qty = envelope.as_int(payload, "on_hand_qty", minimum=0)
    product = lookup.product(product_id)

    position_id = payload.get("inventory_position_id")
    if position_id is not None:
        position = store.positions.get(envelope.as_str(payload, "inventory_position_id"))
        if position is None or position.get("route_id") != route["id"]:
            fail("ERR_INVENTORY_POSITION_NOT_FOUND")
        position["on_hand_qty"] = on_hand_qty
        position["remaining_qty"] = on_hand_qty - position.get("reserved_qty", 0)
        store.stamp(position)
    else:
        if lookup.inventory_position_for(route["id"], product["id"]) is not None:
            fail("ERR_INVENTORY_POSITION_DUPLICATE")
        position = store.create(
            store.positions,
            route_id=route["id"],
            product_id=product["id"],
            unit_cost_cents=product.get("unit_cost_cents", 0),
            on_hand_qty=on_hand_qty,
            reserved_qty=0,
            remaining_qty=on_hand_qty,
        )
    recompute.recompute_route(route)
    # Section 2.5: recomputing the route's derived aggregates is a modification
    # of the route row, so the route's version advances even when the aggregate
    # happens to hold its previous value.
    store.stamp(route)
    return envelope.ok(position, 201)


@bp.get("/inventory-positions")
def list_positions():
    auth.require(*POSITION_ROLES)
    rows = envelope.filter_query(store.ordered(store.positions), {
        "route_id": "route_id",
        "product_id": "product_id",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)
