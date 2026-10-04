"""Customer account, order, and allocation-run routes."""
import uuid
from decimal import Decimal
from flask import Blueprint

import db
from errors import err
from response import (ok, list_response, require_role, require_auth, get_body,
                      req_str, req_enum, req_num, req_int, parse_month)
from services import (get_mill, get_account, get_order, get_grade, new_common,
                      bump, check_occ, require_index, refresh_posture,
                      round_cents, open_scorecard, recompute_scorecard_profit,
                      FORM_TO_CATEGORY)

bp = Blueprint("commercial", __name__)


@bp.route("/mills/<millId>/customer-accounts", methods=["POST"])
def create_account(millId):
    require_role("AccountManager")
    get_mill(millId)
    body = get_body()
    name = req_str(body, "name")
    market = req_enum(body, "market", {"CONSTRUCTION", "AUTOMOTIVE", "ENERGY"})
    mode = req_enum(body, "pricing_mode", {"CONTRACT", "SPOT"})
    acct = {
        "id": str(uuid.uuid4()),
        "mill_id": millId,
        "name": name,
        "market": market,
        "pricing_mode": mode,
        "credit_status": "GOOD",
        "allocation_priority": "STANDARD",
        **new_common(),
    }
    db.accounts[acct["id"]] = acct
    return ok(acct, 201)


@bp.route("/mills/<millId>/customer-accounts", methods=["GET"])
def list_accounts(millId):
    require_auth()
    get_mill(millId)
    rows = [a for a in db.accounts.values() if a["mill_id"] == millId]
    return list_response(rows, {"market": "market", "credit_status": "credit_status"})


@bp.route("/mills/<millId>/customer-accounts/<accountId>", methods=["GET"])
def get_account_route(millId, accountId):
    require_auth()
    get_mill(millId)
    return ok(get_account(accountId, millId))


_CREDIT_NEXT = {
    "GOOD": {"WATCH"},
    "WATCH": {"GOOD", "BLOCKED"},
    "BLOCKED": {"WATCH"},
}


@bp.route("/mills/<millId>/customer-accounts/<accountId>", methods=["PATCH"])
def patch_account(millId, accountId):
    require_role("AccountManager")
    get_mill(millId)
    acct = get_account(accountId, millId)
    body = get_body()
    new_credit = body.get("credit_status")
    new_prio = body.get("allocation_priority")
    if new_credit is None and new_prio is None:
        raise err("ERR_INVALID_REQUEST",
                  "patch requires credit_status and/or allocation_priority")
    if new_credit is not None:
        if new_credit not in ("GOOD", "WATCH", "BLOCKED"):
            raise err("ERR_INVALID_REQUEST", "invalid credit_status")
        if new_credit not in _CREDIT_NEXT[acct["credit_status"]]:
            raise err("ERR_INVALID_STATE",
                      f"cannot move credit_status {acct['credit_status']} -> {new_credit}")
        acct["credit_status"] = new_credit
    if new_prio is not None:
        if new_prio not in ("STANDARD", "STRATEGIC"):
            raise err("ERR_INVALID_REQUEST", "invalid allocation_priority")
        if new_prio == acct["allocation_priority"]:
            raise err("ERR_INVALID_STATE", "allocation_priority already set")
        acct["allocation_priority"] = new_prio
    bump(acct)
    return ok(acct)


# --- orders -------------------------------------------------------------------

def _price_order(mill_id, order, account, at_confirm):
    grade = db.grades[order["grade_id"]]
    cat = FORM_TO_CATEGORY[grade["product_form"]]
    if account["pricing_mode"] == "CONTRACT" and at_confirm:
        month = order["fulfillment_month"]
        basis = "CONTRACT_MONTH_INDEX"
    else:
        month = db.get_clock().strftime("%Y-%m")
        basis = "CURRENT_MONTH_INDEX"
    idx = require_index(mill_id, cat, month)
    unit = order["base_price_cents_per_ton"] + idx["price_per_ton_cents"]
    price = round_cents(Decimal(unit) * Decimal(str(order["tons"])))
    return price, basis


@bp.route("/mills/<millId>/customer-accounts/<accountId>/orders", methods=["POST"])
def create_order(millId, accountId):
    require_role("AccountManager")
    get_mill(millId)
    acct = get_account(accountId, millId)
    body = get_body()
    family = req_enum(body, "product_family", {"REBAR", "BEAM", "PLATE", "WIRE_ROD"})
    grade_id = req_str(body, "grade_id")
    tons = req_num(body, "tons", gt=0)
    month = parse_month(req_str(body, "fulfillment_month"), "fulfillment_month")
    base = req_int(body, "base_price_cents_per_ton", gt=0)
    get_grade(grade_id, millId)
    order = {
        "id": str(uuid.uuid4()),
        "account_id": accountId,
        "mill_id": millId,
        "product_family": family,
        "grade_id": grade_id,
        "tons": tons,
        "fulfillment_month": month,
        "base_price_cents_per_ton": base,
        "allocated_tons": 0.0,
        "computed_price_cents": None,
        "price_basis": None,
        "status": "QUOTED",
        **new_common(),
    }
    db.orders[order["id"]] = order
    return ok(order, 201)


@bp.route("/mills/<millId>/customer-accounts/<accountId>/orders", methods=["GET"])
def list_orders(millId, accountId):
    require_auth()
    get_mill(millId)
    get_account(accountId, millId)
    rows = [o for o in db.orders.values() if o["account_id"] == accountId]
    return list_response(rows, {"status": "status", "grade_id": "grade_id"})


@bp.route("/mills/<millId>/orders/<orderId>", methods=["GET"])
def get_order_flat_in_mill(millId, orderId):
    require_auth()
    get_mill(millId)
    order = get_order(orderId)
    if order["mill_id"] != millId:
        raise err("ERR_ORDER_NOT_FOUND", "order not found in mill")
    return ok(order)


@bp.route("/mills/<millId>/customer-accounts/<accountId>/orders/<orderId>/confirm", methods=["POST"])
def confirm_order(millId, accountId, orderId):
    require_role("AccountManager")
    get_mill(millId)
    acct = get_account(accountId, millId)
    order = get_order(orderId, accountId)
    body = get_body()
    if "expected_order_version" not in body:
        raise err("ERR_INVALID_REQUEST", "expected_order_version is required")
    expected = body.get("expected_order_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_order_version must be an integer")
    check_occ(order, expected)
    refresh_posture(millId)
    if order["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "order must be QUOTED")
    if db.mills[millId]["posture"] != "NORMAL":
        raise err("ERR_MILL_INTERRUPTED", "order book frozen while mill interrupted")
    if acct["credit_status"] == "BLOCKED":
        raise err("ERR_ACCOUNT_BLOCKED", "account is BLOCKED")
    price, basis = _price_order(millId, order, acct, at_confirm=True)
    order["computed_price_cents"] = price
    order["price_basis"] = basis
    order["status"] = "CONFIRMED"
    bump(order)
    return ok(order)


@bp.route("/mills/<millId>/customer-accounts/<accountId>/orders/<orderId>/invoice", methods=["POST"])
def invoice_order(millId, accountId, orderId):
    require_role("AccountManager")
    get_mill(millId)
    acct = get_account(accountId, millId)
    order = get_order(orderId, accountId)
    if order["status"] != "ALLOCATED":
        raise err("ERR_INVALID_STATE", "order must be ALLOCATED")
    if acct["credit_status"] == "BLOCKED":
        raise err("ERR_ACCOUNT_BLOCKED", "account is BLOCKED")
    if acct["pricing_mode"] == "SPOT":
        price, basis = _price_order(millId, order, acct, at_confirm=False)
        order["computed_price_cents"] = price
        order["price_basis"] = basis
    sc = open_scorecard(millId, order["fulfillment_month"])
    if sc is not None:
        sc["revenue_cents"] += order["computed_price_cents"]
        recompute_scorecard_profit(sc)
    order["status"] = "INVOICED"
    bump(order)
    return ok(order)


@bp.route("/mills/<millId>/customer-accounts/<accountId>/orders/<orderId>/cancel", methods=["POST"])
def cancel_order(millId, accountId, orderId):
    require_role("AccountManager")
    get_mill(millId)
    get_account(accountId, millId)
    order = get_order(orderId, accountId)
    if order["status"] not in ("QUOTED", "CONFIRMED", "ALLOCATED"):
        raise err("ERR_INVALID_STATE", "order cannot be cancelled from this state")
    order["allocated_tons"] = 0.0
    order["status"] = "CANCELLED"
    bump(order)
    return ok(order)


# --- allocation runs ------------------------------------------------------------

@bp.route("/mills/<millId>/allocation-runs", methods=["POST"])
def allocation_run(millId):
    require_role("Scheduler")
    get_mill(millId)
    committed_heats = {l["heat_id"] for l in db.campaign_lines.values()}
    heats = [h for h in db.heats.values()
             if h["mill_id"] == millId and h["status"] == "CAST"
             and h["id"] not in committed_heats]
    heats.sort(key=lambda h: (h["planned_tap_at"], h["created_at"]))
    orders = []
    for o in db.orders.values():
        if o["mill_id"] != millId or o["status"] != "CONFIRMED":
            continue
        acct = db.accounts[o["account_id"]]
        if acct["credit_status"] == "BLOCKED":
            continue
        if o["allocated_tons"] >= o["tons"]:
            continue
        orders.append((acct, o))
    orders.sort(key=lambda t: (
        0 if t[0]["allocation_priority"] == "STRATEGIC" else 1,
        t[1]["created_at"],
    ))
    pool = {h["id"]: h["target_tap_weight_tons"] for h in heats}
    heat_order = [h["id"] for h in heats]
    assigned_orders = 0
    assigned_tons = 0.0
    for acct, order in orders:
        need = float(Decimal(str(order["tons"])) - Decimal(str(order["allocated_tons"])))
        got = 0.0
        for hid in heat_order:
            if need <= 0:
                break
            avail = pool.get(hid, 0.0)
            if avail <= 0:
                continue
            take = min(avail, need)
            pool[hid] = float(Decimal(str(avail)) - Decimal(str(take)))
            need = float(Decimal(str(need)) - Decimal(str(take)))
            got = float(Decimal(str(got)) + Decimal(str(take)))
        if got > 0:
            order["allocated_tons"] = float(Decimal(str(order["allocated_tons"])) + Decimal(str(got)))
            if order["allocated_tons"] >= order["tons"]:
                order["status"] = "ALLOCATED"
            bump(order)
            assigned_orders += 1
            assigned_tons = float(Decimal(str(assigned_tons)) + Decimal(str(got)))
    return ok({"assigned_orders": assigned_orders, "assigned_tons": assigned_tons})


# --- flat reads ---------------------------------------------------------------

@bp.route("/mills/customer-accounts", methods=["GET"])
def flat_list_accounts():
    require_auth()
    return list_response(list(db.accounts.values()),
                         {"mill_id": "mill_id", "market": "market",
                          "credit_status": "credit_status"})


@bp.route("/mills/customer-accounts/<accountId>", methods=["GET"])
def flat_get_account(accountId):
    require_auth()
    return ok(get_account(accountId))


@bp.route("/mills/orders", methods=["GET"])
def flat_list_orders():
    require_auth()
    return list_response(list(db.orders.values()),
                         {"account_id": "account_id", "mill_id": "mill_id",
                          "grade_id": "grade_id", "status": "status"})


@bp.route("/mills/orders/<orderId>", methods=["GET"])
def flat_get_order(orderId):
    require_auth()
    return ok(get_order(orderId))
