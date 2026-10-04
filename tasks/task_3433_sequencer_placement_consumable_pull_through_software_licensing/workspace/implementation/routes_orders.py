"""Reagent order endpoints: create, reads, advance (SUBMIT/SHIP/DELIVER/
CANCEL/RETURN) with FEFO allocation and program attribution."""

from flask import Blueprint, request

from auth import require_action_role, require_ownership, require_roles
from calc import allocate_order_lines, committed_total_cents
from envelope import ok, ok_list, sort_items
from errors import ApiError, invalid_state, not_found
from serializers import order_json
from store import DB, new_id, now, stamp_new, touch
from validate import (
    account_credit_hold,
    f_enum,
    f_list,
    f_str,
    get_body,
    kit_by_code,
    resolve_line_kit_codes,
)

bp = Blueprint("orders", __name__)

ADVANCE_ACTIONS = {
    "SUBMIT": "LabOperator",
    "CANCEL": "LabOperator",
    "RETURN": "LabOperator",
    "SHIP": "SupplyPlanner",
    "DELIVER": "SupplyPlanner",
}


def _validate_lines(body):
    lines = f_list(body, "lines")
    if not lines:
        raise ApiError("ERR_INVALID_REQUEST", 400, "lines must contain at least one entry")
    parsed = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "lines entries must be objects")
        kit_code = ln.get("kit_code")
        quantity = ln.get("quantity")
        if not isinstance(kit_code, str) or kit_code == "":
            raise ApiError("ERR_INVALID_REQUEST", 400, "lines.kit_code must be a non-empty string")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "lines.quantity must be an integer >= 1")
        parsed.append({"kit_code": kit_code, "quantity": quantity})
    return parsed


@bp.post("/genomics/reagent-orders")
def create_order():
    uid, _role = require_roles("LabOperator")
    body = get_body()
    # Priority 4: LabOperator ownership — account_id must equal X-User-ID.
    raw_account = body.get("account_id")
    if isinstance(raw_account, str) and raw_account:
        require_ownership(raw_account == uid)
    # Priority 6: body references resolve before shape checks.
    raw_program = body.get("program_id")
    if isinstance(raw_program, str) and raw_program and raw_program not in DB["programs"]:
        raise not_found("program_id does not resolve")
    resolve_line_kit_codes(body.get("lines"))
    # Priority 7: request shape.
    account_id = f_str(body, "account_id")
    require_ownership(account_id == uid)
    program_id = body.get("program_id")
    if program_id is not None and (not isinstance(program_id, str) or program_id == ""):
        raise ApiError("ERR_INVALID_REQUEST", 400, "program_id must be a string")
    lines = _validate_lines(body)
    order = {
        "id": new_id(),
        "account_id": account_id,
        "program_id": program_id,
        "lines": lines,
        "order_state": "DRAFT",
        "total_cents": None,  # priced at SUBMIT
        "attributed_total_cents": None,
        "line_reservations": [],
        "submitted_at": None,
        "delivered_at": None,
    }
    stamp_new(order)
    DB["orders"][order["id"]] = order
    return ok(order_json(order), 201)


@bp.get("/genomics/reagent-orders/<order_id>")
def get_order(order_id):
    uid, role = require_roles("LabOperator", "AccountManager", "SupplyPlanner")
    order = DB["orders"].get(order_id)
    if order is None:
        raise not_found("ReagentOrder not found")
    if role == "LabOperator":
        require_ownership(order["account_id"] == uid)
    return ok(order_json(order))


@bp.get("/genomics/reagent-orders")
def list_orders():
    uid, role = require_roles("LabOperator", "AccountManager", "SupplyPlanner")
    items = list(DB["orders"].values())
    if role == "LabOperator":
        items = [o for o in items if o["account_id"] == uid]  # auto-scoped
    else:
        account_id = request.args.get("account_id")
        if account_id is not None:
            items = [o for o in items if o["account_id"] == account_id]
    program_id = request.args.get("program_id")
    order_state = request.args.get("order_state")
    if program_id is not None:
        items = [o for o in items if o["program_id"] == program_id]
    if order_state is not None:
        items = [o for o in items if o["order_state"] == order_state]
    return ok_list([order_json(o) for o in sort_items(items)])


def _order_submit(order, t):
    if order["order_state"] != "DRAFT":
        raise invalid_state("SUBMIT requires order_state DRAFT")
    program = DB["programs"].get(order["program_id"]) if order["program_id"] else None
    if order["program_id"] and (program is None or program["program_state"] != "ACTIVE"):
        raise ApiError(
            "ERR_PROGRAM_NOT_ACTIVE", 409, "Referenced placement program is not ACTIVE"
        )
    account = DB["accounts"].get(order["account_id"])
    if account is not None and account_credit_hold(account):
        raise ApiError("ERR_CREDIT_HOLD", 402, "Account is on credit hold")
    reservations = allocate_order_lines(order["lines"])
    if reservations is None:
        raise ApiError(
            "ERR_ALLOCATION_IMPOSSIBLE",
            422,
            "FEFO allocation cannot fully satisfy every order line",
        )
    # Pricing at submission: pinned program prices when attributed.
    total = 0
    pinned = program["pinned_kit_prices"] if program is not None else None
    for ln in order["lines"]:
        kit = kit_by_code(ln["kit_code"])
        price = None
        if pinned:
            price = pinned.get(ln["kit_code"])
        if price is None:
            price = kit["price_cents"] if kit is not None else 0
        total += ln["quantity"] * price
    order["total_cents"] = total
    order["attributed_total_cents"] = total if program is not None else 0
    for r in reservations:
        lot = DB["lots"][r["lot_id"]]
        lot["reserved_units"] += r["quantity"]
        touch(lot)
    order["line_reservations"] = reservations
    if program is not None:
        program["pipeline_spend_cents"] += order["attributed_total_cents"]
        touch(program)
    order["submitted_at"] = t
    order["order_state"] = "ALLOCATED"
    touch(order)


def _order_ship(order, t):
    if order["order_state"] != "ALLOCATED":
        raise invalid_state("SHIP requires order_state ALLOCATED")
    # Cold-chain gate (priority 19) precedes the expiry gate (priority 20).
    for r in order["line_reservations"]:
        lot = DB["lots"][r["lot_id"]]
        if lot["cold_chain_status"] != "INTACT":
            raise ApiError(
                "ERR_COLD_CHAIN_BREACHED", 422, "A reserved lot's cold chain is breached"
            )
    for r in order["line_reservations"]:
        lot = DB["lots"][r["lot_id"]]
        if not (lot["expiry_date"] > t):
            raise ApiError("ERR_LOT_EXPIRED", 422, "A reserved lot has expired")
    order["order_state"] = "SHIPPED"
    touch(order)


def _order_deliver(order, t):
    if order["order_state"] != "SHIPPED":
        raise invalid_state("DELIVER requires order_state SHIPPED")
    order["delivered_at"] = t
    for r in order["line_reservations"]:
        lot = DB["lots"][r["lot_id"]]
        lot["reserved_units"] -= r["quantity"]
        lot["consumed_units"] += r["quantity"]
        touch(lot)
    program = DB["programs"].get(order["program_id"]) if order["program_id"] else None
    if program is not None:
        program["pipeline_spend_cents"] -= order["attributed_total_cents"]
        program["delivered_spend_cents"] += order["attributed_total_cents"]
        if (
            program["program_state"] == "ACTIVE"
            and program["delivered_spend_cents"] >= committed_total_cents(program)
        ):
            program["program_state"] = "COMPLETED"
        touch(program)
    order["order_state"] = "DELIVERED"
    touch(order)


def _order_cancel(order):
    if order["order_state"] not in ("DRAFT", "ALLOCATED", "BACKORDERED"):
        raise invalid_state("CANCEL requires DRAFT, ALLOCATED or BACKORDERED")
    if order["order_state"] == "ALLOCATED":
        for r in order["line_reservations"]:
            lot = DB["lots"][r["lot_id"]]
            lot["reserved_units"] -= r["quantity"]
            touch(lot)
        order["line_reservations"] = []
        program = DB["programs"].get(order["program_id"]) if order["program_id"] else None
        if program is not None:
            program["pipeline_spend_cents"] -= order["attributed_total_cents"]
            touch(program)
    order["order_state"] = "CANCELLED"
    touch(order)


def _order_return(order):
    if order["order_state"] != "DELIVERED":
        raise invalid_state("RETURN requires order_state DELIVERED")
    program = DB["programs"].get(order["program_id"]) if order["program_id"] else None
    if program is not None:
        program["delivered_spend_cents"] -= order["attributed_total_cents"]
        touch(program)
    account = DB["accounts"].get(order["account_id"])
    if account is not None:
        account["credit_balance_cents"] += order["total_cents"] or 0
        touch(account)
    # Returned units are never restocked to any lot.
    order["order_state"] = "RETURNED"
    touch(order)


@bp.post("/genomics/reagent-orders/<order_id>/advance")
def advance_order(order_id):
    uid, role = require_roles("LabOperator", "SupplyPlanner")
    body = get_body()
    require_action_role(role, body.get("action"), ADVANCE_ACTIONS)
    order = DB["orders"].get(order_id)
    if order is None:
        raise not_found("ReagentOrder not found")
    if role == "LabOperator":
        require_ownership(order["account_id"] == uid)
    action = f_enum(body, "action", list(ADVANCE_ACTIONS.keys()))
    t = now()
    if action == "SUBMIT":
        _order_submit(order, t)
    elif action == "SHIP":
        _order_ship(order, t)
    elif action == "DELIVER":
        _order_deliver(order, t)
    elif action == "CANCEL":
        _order_cancel(order)
    else:  # RETURN
        _order_return(order)
    return ok(order_json(order))
