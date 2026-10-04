"""Replenishment orders: ceiling fill, shipping, receiving and allocation."""

from flask import Blueprint

import auth
import calc
import envelope
import lookup
import recompute
import store
from errors import fail

bp = Blueprint("product_orders", __name__, url_prefix="/retail")

PRODUCT_ORDER_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer")
MIX_PROFILES = ("DIAGNOSTIC_WEIGHTED", "TOOL_STORAGE", "POWER_TOOLS")
ORDER_ACTIONS = ("SUBMIT", "SHIP", "RECEIVE", "ALLOCATE", "CANCEL")


def parse_requested_lines(raw_lines):
    if not isinstance(raw_lines, list):
        fail("ERR_INVALID_REQUEST", "requested_lines must be an array.")
    lines = []
    for index, entry in enumerate(raw_lines):
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each requested line must be an object.")
        product_id = entry.get("product_id")
        if not isinstance(product_id, str) or not product_id:
            fail("ERR_INVALID_REQUEST", "requested_lines[].product_id is required.")
        qty = entry.get("requested_qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            fail("ERR_INVALID_REQUEST",
                 "requested_lines[].requested_qty must be a non-negative integer.")
        lookup.product(product_id)
        lines.append({"product_id": product_id, "requested_qty": qty, "line_index": index})
    return lines


def requested_cost(lines):
    total = 0
    for line in lines:
        product = store.products[line["product_id"]]
        total += line["requested_qty"] * product.get("unit_cost_cents", 0)
    return total


def apply_allocation(order):
    products = store.products
    ordered, deferred, cost, covered = calc.route_replenishment_allocation(
        order.get("investment_ceiling_cents", 0),
        order.get("requested_lines", []),
        products,
        order.get("mix_profile"),
    )
    order["ordered_lines"] = ordered
    order["deferred_lines"] = deferred
    order["ordered_cost_cents"] = cost
    order["is_fully_covered"] = covered
    store.stamp(order)


@bp.post("/routes/<route_id>/product-orders")
def create_product_order(route_id):
    user_id, role = auth.require("FranchiseOwner")
    route = lookup.route(route_id)
    auth.ensure_owned(user_id, role, route.get("franchisee_id"))
    payload = envelope.body()
    mix_profile = envelope.as_enum(payload, "mix_profile", MIX_PROFILES)
    investment_ceiling_cents = envelope.as_int(payload, "investment_ceiling_cents", minimum=0)
    lines = parse_requested_lines(payload.get("requested_lines"))
    cost = requested_cost(lines)
    if cost > investment_ceiling_cents:
        fail("ERR_ALLOCATION_CEILING_EXCEEDED")

    ordered, deferred, ordered_cost, covered = calc.route_replenishment_allocation(
        investment_ceiling_cents, lines, store.products, mix_profile)
    order = store.create(
        store.product_orders,
        route_id=route["id"],
        product_order_status="DRAFT",
        mix_profile=mix_profile,
        investment_ceiling_cents=investment_ceiling_cents,
        requested_lines=lines,
        requested_cost_cents=cost,
        ordered_lines=ordered,
        deferred_lines=deferred,
        ordered_cost_cents=ordered_cost,
        is_fully_covered=covered,
    )
    return envelope.ok(order, 201)


@bp.get("/product-orders")
def list_product_orders():
    auth.require(*PRODUCT_ORDER_ROLES)
    rows = envelope.filter_query(store.ordered(store.product_orders), {
        "route_id": "route_id",
        "product_order_status": "product_order_status",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.get("/product-orders/<order_id>")
def get_product_order(order_id):
    auth.require(*PRODUCT_ORDER_ROLES)
    return envelope.ok(lookup.product_order(order_id))


def pledges_of(order_id):
    return [p for p in store.pledges.values() if p.get("product_order_id") == order_id]


@bp.post("/product-orders/<order_id>/status")
def advance_product_order(order_id):
    user_id, role = auth.require("FranchiseOwner", "FranchiseManager")
    order = lookup.product_order(order_id)
    auth.ensure_owned(user_id, role, order.get("route_id") and
                      auth.route_owner_id(store.routes.get(order.get("route_id"))))
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", ORDER_ACTIONS)

    expected = payload.get("expected_product_order_version")
    if action == "RECEIVE":
        if expected is None:
            fail("ERR_INVALID_REQUEST",
                 "expected_product_order_version is required to receive an order.")
        if isinstance(expected, bool) or not isinstance(expected, int):
            fail("ERR_INVALID_REQUEST", "expected_product_order_version must be an integer.")
        if expected != order.get("version"):
            fail("ERR_STALE_VERSION")
    elif expected is not None:
        fail("ERR_INVALID_REQUEST",
             "expected_product_order_version is only accepted by the receive action.")

    status = order.get("product_order_status")
    if action == "SUBMIT":
        if status != "DRAFT":
            fail("ERR_INVALID_STATE")
        if not order.get("requested_lines"):
            fail("ERR_EMPTY_MIX_LINES")
        if order.get("requested_cost_cents", 0) > order.get("investment_ceiling_cents", 0):
            fail("ERR_ALLOCATION_CEILING_EXCEEDED")
        store.set_field(order, "product_order_status", "SUBMITTED")
        apply_allocation(order)
    elif action == "SHIP":
        if status != "SUBMITTED":
            fail("ERR_INVALID_STATE")
        for pledge in pledges_of(order["id"]):
            if pledge.get("pledge_status") not in ("BOUND", "RELEASED"):
                fail("ERR_INVALID_STATE", "A share pledge is still merely HELD.")
        store.set_field(order, "product_order_status", "SHIPPED")
    elif action == "RECEIVE":
        if status != "SHIPPED":
            fail("ERR_INVALID_STATE")
        route = lookup.route(order.get("route_id"))
        for line in order.get("ordered_lines", []):
            if line.get("ordered_qty", 0) <= 0:
                continue
            position = lookup.inventory_position_for(route["id"], line["product_id"])
            if position is None:
                position = store.create(
                    store.positions,
                    route_id=route["id"],
                    product_id=line["product_id"],
                    unit_cost_cents=line.get("unit_cost_cents", 0),
                    on_hand_qty=0,
                    reserved_qty=0,
                    remaining_qty=0,
                )
            position["on_hand_qty"] = position.get("on_hand_qty", 0) + line["ordered_qty"]
            position["remaining_qty"] = position["on_hand_qty"] - position.get("reserved_qty", 0)
            store.stamp(position)
        store.set_field(order, "product_order_status", "RECEIVED")
        recompute.recompute_route(route)
    elif action == "ALLOCATE":
        if status != "RECEIVED":
            fail("ERR_INVALID_STATE")
        pledges = pledges_of(order["id"])
        for pledge in pledges:
            if pledge.get("pledge_status") != "BOUND":
                fail("ERR_INVALID_STATE", "Every share pledge must be BOUND before allocation.")
        route_id = order.get("route_id")
        sustained = calc.mixed_inventory_plan(
            [p for p in pledges if p.get("pledge_status") in ("HELD", "BOUND")],
            lambda _route, product_id: lookup.inventory_position_for(route_id, product_id),
        )
        for pledge in pledges:
            store.set_field(pledge, "pledge_status", "CONSUMED")
            store.set_field(pledge, "sustained_amount_cents", sustained.get(pledge["id"], 0))
            account = store.accounts.get(pledge.get("credit_account_id"))
            if account is not None:
                recompute.recompute_account(account)
        store.set_field(order, "product_order_status", "ALLOCATED")
    else:
        if status not in ("DRAFT", "SUBMITTED", "SHIPPED", "RECEIVED"):
            fail("ERR_INVALID_STATE")
        for pledge in pledges_of(order["id"]):
            store.set_field(pledge, "pledge_status", "RELEASED")
        store.set_field(order, "product_order_status", "CANCELLED")

    store.stamp(order)
    return envelope.ok(order)
