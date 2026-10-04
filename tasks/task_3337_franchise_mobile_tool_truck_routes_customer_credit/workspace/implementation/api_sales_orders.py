"""Sales orders: creation, line editing and fulfilment."""

from flask import Blueprint

import auth
import calc
import clock
import envelope
import lookup
import recompute
import store
from errors import fail

bp = Blueprint("sales_orders", __name__, url_prefix="/retail")

ORDER_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer",
               "RouteSalesRep", "Technician", "WarrantyAdmin")
MIX_PROFILES = ("DIAGNOSTIC_WEIGHTED", "TOOL_STORAGE", "POWER_TOOLS")
ORDER_ACTIONS = ("CONFIRM", "DELIVER", "SETTLE", "CANCEL")


def parse_lines(raw_lines):
    if not isinstance(raw_lines, list) or not raw_lines:
        fail("ERR_EMPTY_MIX_LINES")
    lines = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each line must be an object.")
        product_id = entry.get("product_id")
        if not isinstance(product_id, str) or not product_id:
            fail("ERR_INVALID_REQUEST", "line.product_id is required.")
        quantity = entry.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            fail("ERR_INVALID_REQUEST", "line.quantity must be a non-negative integer.")
        unit_price = entry.get("unit_price_cents")
        if isinstance(unit_price, bool) or not isinstance(unit_price, int) or unit_price < 0:
            fail("ERR_INVALID_REQUEST", "line.unit_price_cents must be a non-negative integer.")
        terms = entry.get("warranty_terms") or {}
        if not isinstance(terms, dict):
            fail("ERR_INVALID_REQUEST", "line.warranty_terms must be an object.")
        months = terms.get("months", 0)
        if isinstance(months, bool) or not isinstance(months, int) or months < 0:
            fail("ERR_INVALID_REQUEST", "warranty_terms.months must be a non-negative integer.")
        lines.append({
            "product_id": product_id,
            "quantity": quantity,
            "unit_price_cents": unit_price,
            "warranty_terms": {"type": terms.get("type"), "months": months},
        })
    return lines


def check_stock(route, lines):
    for line in lines:
        position = lookup.inventory_position_for(route["id"], line["product_id"])
        if position is None:
            fail("ERR_INVENTORY_POSITION_NOT_FOUND")
        if line["quantity"] > position.get("remaining_qty", 0):
            fail("ERR_INSUFFICIENT_INVENTORY")


@bp.post("/routes/<route_id>/sales-orders")
def create_order(route_id):
    user_id, role = auth.require("RouteSalesRep")
    route = lookup.route(route_id)
    auth.ensure_owned(user_id, role, route.get("franchisee_id"))
    payload = envelope.body()
    technician_id = envelope.as_str(payload, "technician_id")
    credit_account_id = envelope.as_str(payload, "credit_account_id")
    mix_profile = envelope.as_enum(payload, "mix_profile", MIX_PROFILES)
    lines = parse_lines(payload.get("lines"))

    technician = lookup.technician(technician_id)
    account = lookup.account(credit_account_id)
    for line in lines:
        lookup.product(line["product_id"])
    check_stock(route, lines)

    gross = calc.order_gross_total(lines, mix_profile)
    order = store.create(
        store.sales_orders,
        route_id=route["id"],
        technician_id=technician["id"],
        credit_account_id=account["id"],
        mix_profile=mix_profile,
        lines=lines,
        order_status="DRAFT",
        sale_iso_week=clock.fmt_week(clock.current_week_start()),
        line_count=len(lines),
        gross_total_cents=gross,
        financed_principal_cents=gross,
    )
    return envelope.ok(order, 201)


@bp.get("/sales-orders")
def list_orders():
    user_id, role = auth.require(*ORDER_ROLES)
    rows = store.ordered(store.sales_orders)
    if role == "Technician":
        rows = [o for o in rows if o.get("technician_id") == user_id]
    rows = envelope.filter_query(rows, {
        "route_id": "route_id",
        "technician_id": "technician_id",
        "credit_account_id": "credit_account_id",
        "order_status": "order_status",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.get("/sales-orders/<order_id>")
def get_order(order_id):
    user_id, role = auth.require(*ORDER_ROLES)
    order = lookup.sales_order(order_id)
    if role == "Technician":
        auth.ensure_technician_self(user_id, role, order.get("technician_id"))
    return envelope.ok(order)


@bp.patch("/sales-orders/<order_id>")
def edit_order(order_id):
    user_id, role = auth.require("RouteSalesRep")
    order = lookup.sales_order(order_id)
    auth.ensure_owned(user_id, role, auth.order_owner_id(order))
    if order.get("order_status") != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT order's line set may be replaced.")
    payload = envelope.body()
    if payload.get("mix_profile") is not None:
        store.set_field(order, "mix_profile",
                        envelope.as_enum(payload, "mix_profile", MIX_PROFILES))
    if payload.get("lines") is not None:
        lines = parse_lines(payload.get("lines"))
        route = lookup.route(order.get("route_id"))
        for line in lines:
            lookup.product(line["product_id"])
        check_stock(route, lines)
        order["lines"] = lines
    store.stamp(order)
    recompute.recompute_order(order)
    return envelope.ok(order)


@bp.post("/sales-orders/<order_id>/status")
def advance_order(order_id):
    user_id, role = auth.require("RouteSalesRep")
    order = lookup.sales_order(order_id)
    auth.ensure_owned(user_id, role, auth.order_owner_id(order))
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", ORDER_ACTIONS)

    expected = payload.get("expected_sales_order_version")
    if action == "CONFIRM":
        if expected is None:
            fail("ERR_INVALID_REQUEST",
                 "expected_sales_order_version is required to confirm an order.")
        if isinstance(expected, bool) or not isinstance(expected, int):
            fail("ERR_INVALID_REQUEST", "expected_sales_order_version must be an integer.")
        if expected != order.get("version"):
            fail("ERR_STALE_VERSION")
    elif expected is not None:
        fail("ERR_INVALID_REQUEST",
             "expected_sales_order_version is only accepted by the confirm action.")

    status = order.get("order_status")
    if action == "CONFIRM":
        _confirm(order, status)
    elif action == "DELIVER":
        _deliver(order, status)
    elif action == "SETTLE":
        _settle(order, status)
    else:
        _cancel(order, status)

    store.stamp(order)
    recompute.recompute_order(order)
    route = store.routes.get(order.get("route_id"))
    if route:
        recompute.recompute_route(route)
    return envelope.ok(order)


def _confirm(order, status):
    if status != "DRAFT":
        fail("ERR_ORDER_NOT_CONFIRMABLE")
    lines = order.get("lines", [])
    if len(lines) < 1:
        fail("ERR_EMPTY_MIX_LINES")
    account = lookup.account(order.get("credit_account_id"))
    if account.get("account_status") != "ACTIVE":
        fail("ERR_ACCOUNT_NOT_ACTIVE")
    route = lookup.route(order.get("route_id"))
    technician = lookup.technician(order.get("technician_id"))
    check_stock(route, lines)
    if technician.get("home_route_id") != route["id"]:
        fail("ERR_INVALID_STATE", "The buyer's home route is not this order's route.")
    for line in lines:
        position = lookup.inventory_position_for(route["id"], line["product_id"])
        position["reserved_qty"] = position.get("reserved_qty", 0) + line["quantity"]
        position["remaining_qty"] = position.get("on_hand_qty", 0) - position["reserved_qty"]
        store.stamp(position)
    store.set_field(order, "order_status", "CONFIRMED")
    recompute.recompute_order(order)
    recompute.recompute_route(route)
    recompute.recompute_account(account)


def _deliver(order, status):
    if status != "CONFIRMED":
        fail("ERR_ORDER_NOT_DELIVERABLE")
    lines = order.get("lines", [])
    account = lookup.account(order.get("credit_account_id"))
    # State admissibility (Section 3.9, sixth) is evaluated before the fiscal
    # ceilings (last): financing requires an ACTIVE account.
    if account.get("account_status") != "ACTIVE":
        fail("ERR_ACCOUNT_NOT_ACTIVE")
    technician = lookup.technician(order.get("technician_id"))
    gross = calc.order_gross_total(lines, order.get("mix_profile"))
    financed = gross - sum(recompute.approved_claim_allocations(order["id"]))
    if financed > account.get("credit_available_cents", 0):
        fail("ERR_ACCOUNT_LIMIT_EXCEEDED")
    if account.get("account_kind") == "REVOLVING":
        headroom = max(0, technician.get("credit_line_limit_cents", 0)
                       - technician.get("revolving_used_cents", 0))
        if financed > headroom:
            fail("ERR_CREDIT_LIMIT_EXCEEDED")

    route = lookup.route(order.get("route_id"))
    for line in lines:
        position = lookup.inventory_position_for(route["id"], line["product_id"])
        if position is None:
            fail("ERR_INVENTORY_POSITION_NOT_FOUND")
        position["on_hand_qty"] = position.get("on_hand_qty", 0) - line["quantity"]
        position["reserved_qty"] = position.get("reserved_qty", 0) - line["quantity"]
        position["remaining_qty"] = position["on_hand_qty"] - position["reserved_qty"]
        store.stamp(position)
    order["financed_principal_cents"] = financed
    store.set_field(order, "order_status", "DELIVERED")
    account["principal_balance_cents"] = account.get("principal_balance_cents", 0) + financed
    store.stamp(account)
    recompute.recompute_account(account)
    recompute.recompute_account_dependants(account)
    recompute.recompute_route(route)


def _settle(order, status):
    if status != "DELIVERED":
        fail("ERR_ORDER_NOT_SETTLEABLE")
    for claim in store.claims.values():
        if claim.get("order_id") == order["id"] and claim.get("claim_status") in ("OPEN", "SUBMITTED"):
            fail("ERR_ORDER_NOT_SETTLEABLE")
    store.set_field(order, "order_status", "SETTLED")


def _cancel(order, status):
    if status not in ("DRAFT", "CONFIRMED"):
        fail("ERR_INVALID_STATE")
    route = store.routes.get(order.get("route_id"))
    if status == "CONFIRMED" and route:
        for line in order.get("lines", []):
            position = lookup.inventory_position_for(route["id"], line["product_id"])
            if position is None:
                continue
            position["reserved_qty"] = max(0, position.get("reserved_qty", 0) - line["quantity"])
            position["remaining_qty"] = position.get("on_hand_qty", 0) - position["reserved_qty"]
            store.stamp(position)
        recompute.recompute_route(route)
    store.set_field(order, "order_status", "CANCELLED")
