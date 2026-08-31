"""Orders, order lines, submission, allocation and cancellation."""
from datetime import timedelta

from flask import Blueprint

import calc
from common import (
    ALL_ROLES, ApiError, DB, D, authenticate, f_date, f_int, f_str, get_body,
    must, new_row, now_date, ok, page, public, qp, scope, sort_rows, touch,
)

bp = Blueprint("orders", __name__, url_prefix="/distribution")

ORDER_READERS = ALL_ROLES
ORDER_LIST_ROLES = ["PlatformAdmin", "SalesRep", "WarehouseOperator", "ComplianceOfficer", "Customer"]


def _customer_scope_filter(rows, role, user_id, account_of):
    if role != "Customer":
        return rows
    requested = qp("account_id")
    if requested is not None and requested != user_id:
        raise ApiError("ERR_ACCOUNT_SCOPE_VIOLATION", "customer may only list its own account")
    return [r for r in rows if account_of(r) == user_id]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@bp.post("/orders")
def create_order():
    user_id, role = authenticate(["SalesRep", "Customer"])
    body = get_body()
    account_id = f_str(body, "account_id")
    warehouse_id = f_str(body, "warehouse_id")
    requested_ship_date = f_date(body, "requested_ship_date")
    storm_event_id = f_str(body, "storm_event_id", required=False, default=None)
    must("accounts", account_id)
    must("warehouses", warehouse_id)
    if storm_event_id is not None:
        must("storm_events", storm_event_id)
    scope(role, user_id, account_id)
    row = new_row({
        "account_id": account_id,
        "warehouse_id": warehouse_id,
        "storm_event_id": storm_event_id,
        "requested_ship_date": requested_ship_date,
        "fulfillment_status": "DRAFT",
        "credit_status": "PENDING",
        "hazmat_hold": False,
        "rejected_carrier_ids": [],
        "line_count": 0,
        "subtotal_cents": 0,
        "core_deposit_charge_cents": 0,
        "hazmat_fee_waived": False,
        "hazmat_fee_cents": 0,
        "service_contract_fee_cents": 0,
        "total_cents": 0,
        "allocation_priority_score": 0,
        "cancellation_reason": None,
    })
    DB.orders[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/orders/<order_id>")
def read_order(order_id):
    user_id, role = authenticate(ORDER_READERS)
    order = must("orders", order_id)
    scope(role, user_id, order["account_id"])
    return ok(public(order))


@bp.get("/orders")
def list_orders():
    user_id, role = authenticate(ORDER_LIST_ROLES)
    rows = list(DB.orders.values())
    rows = _customer_scope_filter(rows, role, user_id, lambda r: r["account_id"])
    for name in ("account_id", "warehouse_id", "storm_event_id", "fulfillment_status", "credit_status"):
        value = qp(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return page(rows, public)


# ---------------------------------------------------------------------------
# Order lines
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/lines")
def create_line(order_id):
    user_id, role = authenticate(["SalesRep", "Customer"])
    order = must("orders", order_id)
    body = get_body()
    model_id = f_str(body, "battery_model_id")
    quantity = f_int(body, "quantity", minimum=1)
    core_expected = f_int(body, "core_expected_count", required=False, default=0, minimum=0)
    if core_expected > quantity:
        raise ApiError("ERR_INVALID_REQUEST", "core_expected_count may not exceed quantity")
    model = must("battery_models", model_id)
    scope(role, user_id, order["account_id"])
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "lines may only be added to a DRAFT order")
    if model["status"] == "DISCONTINUED":
        raise ApiError("ERR_MODEL_DISCONTINUED", "model is discontinued")

    row = new_row({
        "order_id": order_id,
        "battery_model_id": model_id,
        "quantity": quantity,
        "core_expected_count": core_expected,
        "unit_price_cents": 0,
        "discount_pct": 0.0,
        "line_total_cents": 0,
        "allocated_quantity": 0,
        "allocated_lot_id": None,
        "core_due_by": None,
    })
    DB.order_lines[row["id"]] = row
    order["line_count"] = int(order["line_count"]) + 1
    touch(order)
    return ok(public(row), 201)


@bp.get("/order-lines/<line_id>")
def read_line(line_id):
    user_id, role = authenticate(ORDER_LIST_ROLES)
    line = must("order_lines", line_id)
    order = DB.orders[line["order_id"]]
    scope(role, user_id, order["account_id"])
    return ok(public(line))


@bp.get("/order-lines")
def list_lines():
    user_id, role = authenticate(ORDER_LIST_ROLES)
    rows = list(DB.order_lines.values())
    if role == "Customer":
        rows = [r for r in rows if DB.orders[r["order_id"]]["account_id"] == user_id]
    for name in ("order_id", "battery_model_id", "allocated_lot_id"):
        value = qp(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return page(rows, public)


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/submit")
def submit_order(order_id):
    user_id, role = authenticate(["SalesRep", "Customer"])
    order = must("orders", order_id)
    get_body()
    scope(role, user_id, order["account_id"])

    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "order is not in DRAFT")
    account = DB.accounts[order["account_id"]]
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", "account is not ACTIVE")
    lines = calc.order_lines(order_id)
    if len(lines) < 1:
        raise ApiError("ERR_ORDER_HAS_NO_LINES", "order carries no lines")
    for line in lines:
        if DB.battery_models[line["battery_model_id"]]["status"] == "DISCONTINUED":
            raise ApiError("ERR_MODEL_DISCONTINUED", "a line names a discontinued model")

    priced, subtotal = calc.price_lines(order, account, lines)
    waived = subtotal >= calc.HAZMAT_FEE_WAIVER_SUBTOTAL_CENTS
    warehouse = DB.warehouses[order["warehouse_id"]]
    if waived:
        hazmat_fee = 0
    else:
        hazmat_fee = calc.hazmat_surcharge(
            calc.order_class_code(lines), calc.lines_weight_kg(lines), warehouse, 1)
    deposit_charge = calc.core_deposit_charge(lines)
    total = subtotal + deposit_charge + hazmat_fee + int(order["service_contract_fee_cents"])

    headroom = (total + int(account["open_receivable_cents"])
                - int(account["warranty_credit_cents"]))
    if headroom > int(account["credit_limit_cents"]):
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", "credit limit exceeded")

    for line, unit_price, discount, line_total in priced:
        line["unit_price_cents"] = unit_price
        line["discount_pct"] = float(discount)
        line["line_total_cents"] = line_total
        touch(line)

    order["subtotal_cents"] = subtotal
    order["hazmat_fee_waived"] = waived
    order["hazmat_fee_cents"] = hazmat_fee
    order["core_deposit_charge_cents"] = deposit_charge
    order["total_cents"] = total
    order["fulfillment_status"] = "SUBMITTED"
    order["credit_status"] = "CLEARED"
    touch(order)

    calc.adjust_receivable(account, total)
    return ok(public(order))


# ---------------------------------------------------------------------------
# Allocate
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/allocate")
def allocate_order(order_id):
    authenticate(["WarehouseOperator", "PlatformAdmin"])
    order = must("orders", order_id)
    get_body()

    if order["fulfillment_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "order is not SUBMITTED")
    if order["credit_status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE", "order credit status is not CLEARED")

    account = DB.accounts[order["account_id"]]
    lines = calc.order_lines(order_id)
    is_storm = bool(order.get("storm_event_id"))
    event = None
    if is_storm:
        event = DB.storm_events[order["storm_event_id"]]
        if event["status"] != "ALLOCATING":
            raise ApiError("ERR_INVALID_STATE", "storm event is not open for allocation")

    score = calc.allocation_priority_score(order, account, event)
    total_units = sum(int(l["quantity"]) for l in lines)

    if is_storm:
        if account["state_code"] != event["region_state_code"]:
            raise ApiError("ERR_STORM_REGION_MISMATCH", "account state does not match the storm region")
        if score < int(event["min_priority_score"]):
            raise ApiError("ERR_STORM_PRIORITY_TOO_LOW", "allocation priority score below the minimum")
        if total_units > int(event["remaining_pool_units"]):
            raise ApiError("ERR_STORM_POOL_EXHAUSTED", "storm pool is exhausted")

    tentative = {}
    chosen = []
    for line in lines:
        lot = calc.select_lot(order, line, is_storm, tentative)
        tentative[lot["id"]] = tentative.get(lot["id"], 0) + int(line["quantity"])
        chosen.append((line, lot))

    for line, lot in chosen:
        line["allocated_lot_id"] = lot["id"]
        line["allocated_quantity"] = int(line["quantity"])
        touch(line)
        lot["quantity_reserved"] = int(lot["quantity_reserved"]) + int(line["quantity"])
        calc.lot_view(lot)
        touch(lot)

    order["allocation_priority_score"] = score
    order["fulfillment_status"] = "ALLOCATED"
    touch(order)

    if is_storm:
        event["allocated_units"] = int(event["allocated_units"]) + total_units
        event["remaining_pool_units"] = int(event["allocation_pool_units"]) - int(event["allocated_units"])
        touch(event)
    return ok(public(order))


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = authenticate(["SalesRep", "PlatformAdmin", "Customer"])
    order = must("orders", order_id)
    body = get_body()
    reason = f_str(body, "cancellation_reason")
    scope(role, user_id, order["account_id"])

    status = order["fulfillment_status"]
    if status not in ("DRAFT", "SUBMITTED", "ALLOCATED"):
        raise ApiError("ERR_INVALID_STATE", "order cannot be cancelled from %s" % status)

    account = DB.accounts[order["account_id"]]
    lines = calc.order_lines(order_id)

    if status == "ALLOCATED":
        for shipment in sort_rows(list(DB.shipments.values())):
            if shipment["order_id"] != order_id:
                continue
            if shipment["status"] in ("PACKED", "CERTIFIED"):
                if int(order["hazmat_fee_cents"]) == int(shipment["hazmat_surcharge_cents"]) \
                        and shipment["status"] == "CERTIFIED":
                    order["total_cents"] = calc.assemble_total(order)
                shipment["status"] = "VOIDED"
                touch(shipment)

    if status in ("SUBMITTED", "ALLOCATED"):
        calc.adjust_receivable(account, -int(order["total_cents"]))

    if status == "ALLOCATED":
        for line in lines:
            if line["allocated_lot_id"]:
                lot = DB.inventory_lots[line["allocated_lot_id"]]
                lot["quantity_reserved"] = max(0, int(lot["quantity_reserved"]) - int(line["allocated_quantity"]))
                calc.lot_view(lot)
                touch(lot)
                line["allocated_lot_id"] = None
                line["allocated_quantity"] = 0
                touch(line)
        if order.get("storm_event_id"):
            event = DB.storm_events[order["storm_event_id"]]
            total_units = sum(int(l["quantity"]) for l in lines)
            event["allocated_units"] = max(0, int(event["allocated_units"]) - total_units)
            event["remaining_pool_units"] = int(event["allocation_pool_units"]) - int(event["allocated_units"])
            touch(event)

    if status in ("SUBMITTED", "ALLOCATED"):
        for contract in sort_rows(list(DB.service_contracts.values())):
            if contract.get("order_id") == order_id and contract["status"] in ("ATTACHED", "ACTIVE"):
                contract["status"] = "CANCELLED"
                touch(contract)

    order["fulfillment_status"] = "CANCELLED"
    order["credit_status"] = "CLOSED"
    order["cancellation_reason"] = reason
    touch(order)
    return ok(public(order))
