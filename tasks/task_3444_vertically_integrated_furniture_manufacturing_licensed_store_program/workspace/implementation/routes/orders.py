"""Supply orders (PRD §3.5): dual-axis lifecycle, pricing, credit gate, sweep."""
from flask import Blueprint, request

from constants import BUYER_TYPES, DELIVERY_MODES, ORDER_ACTIONS
from db import store
from errors import err
from middleware import auth, require_order_owner, require_role
from routes.cycles import get_cycle
from routes.licensees import get_licensee
from routes.product_lines import get_line
from routes.retail_accounts import get_account
from services import calc
from services.engine import deliver_order, promotion_sweep
from util import (
    get_body, new_record, now_dt, ok_list, ok_object, opt_str, paginate,
    req_enum, req_int, req_str, serialize, touch,
)

bp = Blueprint("orders", __name__)

_ACTION_ROLES = {
    "SUBMIT": ["LicenseeManager", "WholesaleBuyer"],
    "CANCEL": ["LicenseeManager", "WholesaleBuyer", "PlatformAdmin"],
    "PICK": ["LogisticsCoordinator"],
    "SHIP": ["LogisticsCoordinator"],
    "DELIVER": ["LogisticsCoordinator"],
}


def get_order(oid):
    o = store.orders.get(oid)
    if o is None:
        err("ERR_ORDER_NOT_FOUND", "unknown order id")
    return o


@bp.route("/api/orders", methods=["POST"])
def create_order():
    uid, role = auth()
    data = get_body()
    buyer_type = req_enum(data, "buyer_type", BUYER_TYPES)
    licensee_id = data.get("licensee_id")
    retail_account_id = data.get("retail_account_id")
    if licensee_id is not None and not isinstance(licensee_id, str):
        err("ERR_VALIDATION", "licensee_id must be a string or null")
    if retail_account_id is not None and not isinstance(retail_account_id, str):
        err("ERR_VALIDATION", "retail_account_id must be a string or null")
    cycle_id = req_str(data, "allocation_cycle_id")
    line_id = req_str(data, "product_line_id")
    quantity = req_int(data, "quantity", minimum=1)
    delivery_mode = req_enum(data, "delivery_mode", DELIVERY_MODES)
    require_role(role, ["LicenseeManager", "WholesaleBuyer"])
    # Stage 4 ownership straight from body FKs (before existence, per pipeline).
    if role == "LicenseeManager" and licensee_id != uid:
        err("ERR_NOT_RESOURCE_OWNER", "X-User-ID must equal licensee_id")
    if role == "WholesaleBuyer" and retail_account_id != uid:
        err("ERR_NOT_RESOURCE_OWNER", "X-User-ID must equal retail_account_id")
    # Stage 5 existence, body FKs in declared field order.
    if licensee_id is not None:
        get_licensee(licensee_id)
    if retail_account_id is not None:
        get_account(retail_account_id)
    cycle = get_cycle(cycle_id)
    line = get_line(line_id)
    # Stage 7 state guards: cycle OPEN + line orderable (both at create AND submit).
    if cycle["status"] != "OPEN":
        err("ERR_CYCLE_NOT_OPEN", "order create requires an OPEN cycle")
    if line["lifecycle"] not in ("ACTIVE", "CLEARANCE"):
        err("ERR_LINE_NOT_ORDERABLE", "product line is not orderable")
    # Stage 9 domain constraints.
    if buyer_type == "LICENSEE":
        if licensee_id is None or retail_account_id is not None:
            err("ERR_BUYER_MISMATCH", "LICENSEE orders need licensee_id and null retail_account_id")
    else:
        if retail_account_id is None or licensee_id is not None:
            err("ERR_BUYER_MISMATCH", "RETAIL_ACCOUNT orders need retail_account_id and null licensee_id")
    if buyer_type == "RETAIL_ACCOUNT" and delivery_mode == "HOME_DELIVERY":
        err("ERR_DELIVERY_MODE_NOT_ALLOWED", "HOME_DELIVERY is reserved for licensee buyers")
    rec = new_record()
    rec.update({
        "buyer_type": buyer_type,
        "licensee_id": licensee_id,
        "retail_account_id": retail_account_id,
        "allocation_cycle_id": cycle_id,
        "product_line_id": line_id,
        "quantity": quantity,
        "delivery_mode": delivery_mode,
        "unit_price_cents": None,
        "provisional_total_cents": None,
        "final_total_cents": None,
        "allocation_state": "UNALLOCATED",
        "fulfillment_state": "PENDING",
        "submitted_at": None,
        "delivered_at": None,
        "cancel_reason": None,
        "_priced_lifecycle": None,
        "_royalty_cents": None,
        "_reached_allocated": False,
    })
    calc.price_order(rec, line)
    store.orders[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/api/orders/<oid>", methods=["GET"])
def fetch_order(oid):
    auth()
    return ok_object(serialize(get_order(oid)), 200)


@bp.route("/api/orders", methods=["GET"])
def list_orders():
    auth()
    items = list(store.orders.values())
    for field in ("licensee_id", "retail_account_id", "product_line_id",
                  "allocation_cycle_id", "allocation_state", "fulfillment_state"):
        value = request.args.get(field)
        if value is not None:
            items = [o for o in items if o[field] == value]
    page, pagination = paginate(items)
    return ok_list([serialize(o) for o in page], pagination)


@bp.route("/api/orders/<oid>/transition", methods=["POST"])
def transition_order(oid):
    uid, role = auth()
    data = get_body()
    action = req_enum(data, "action", ORDER_ACTIONS)
    reason = opt_str(data, "reason", None)
    require_role(role, ["LicenseeManager", "WholesaleBuyer", "PlatformAdmin", "LogisticsCoordinator"])
    if role not in _ACTION_ROLES[action]:
        err("ERR_FORBIDDEN_ROLE", "role %s may not perform %s" % (role, action))
    order = get_order(oid)
    if action in ("SUBMIT", "CANCEL"):
        require_order_owner(uid, role, order)

    bumped = set()
    if action == "SUBMIT":
        _submit(order, bumped)
    elif action == "CANCEL":
        _cancel(order, reason, bumped)
    elif action == "PICK":
        _pick(order, bumped)
    elif action == "SHIP":
        _ship(order, bumped)
    else:
        _deliver(order, bumped)
    return ok_object(serialize(order), 200)


def _submit(order, bumped):
    if order["allocation_state"] != "UNALLOCATED":
        err("ERR_INVALID_TRANSITION", "only an UNALLOCATED order can be submitted")
    cycle = store.cycles[order["allocation_cycle_id"]]
    line = store.product_lines[order["product_line_id"]]
    # Stage 7 state guards, in the pipeline's stated order.
    if cycle["status"] != "OPEN":
        err("ERR_CYCLE_NOT_OPEN", "order submit requires an OPEN cycle")
    if line["lifecycle"] not in ("ACTIVE", "CLEARANCE"):
        err("ERR_LINE_NOT_ORDERABLE", "product line is no longer orderable")
    account = None
    if order["buyer_type"] == "LICENSEE":
        lic = store.licensees[order["licensee_id"]]
        if lic["status"] not in ("ACTIVE", "PROBATION"):
            err("ERR_LICENSEE_NOT_ORDERABLE", "licensee is not orderable")
    else:
        account = store.retail_accounts[order["retail_account_id"]]
        if account["status"] != "ACTIVE":
            err("ERR_ACCOUNT_ON_HOLD", "retail account is not ACTIVE")
    # Provisional re-price when the line's lifecycle changed since create.
    if line["lifecycle"] != order["_priced_lifecycle"]:
        calc.price_order(order, line)
    # Stage 10: the wholesale credit gate is always last; equality passes.
    if account is not None:
        calc.recompute_credit(account)
        if account["credit_used_cents"] + order["provisional_total_cents"] > account["credit_limit_cents"]:
            err("ERR_CREDIT_LIMIT_EXCEEDED", "submit would exceed the credit limit")
    # Capacity decides the landing state.
    calc.recompute_cycle(cycle)
    order["submitted_at"] = now_dt()
    if cycle["available_units"] >= order["quantity"]:
        order["allocation_state"] = "RESERVED"
    else:
        order["allocation_state"] = "WAITLISTED"
    touch(order, bumped)
    if calc.recompute_cycle(cycle):
        touch(cycle, bumped)
    if account is not None and order["allocation_state"] == "RESERVED":
        if calc.recompute_credit(account):
            touch(account, bumped)


def _cancel(order, reason, bumped):
    if (order["allocation_state"] not in ("RESERVED", "WAITLISTED", "ALLOCATED")
            or order["fulfillment_state"] not in ("PENDING", "PICKED")):
        err("ERR_INVALID_TRANSITION",
            "CANCEL requires allocation RESERVED/WAITLISTED/ALLOCATED and fulfillment PENDING/PICKED")
    if reason is not None:
        order["cancel_reason"] = reason
    order["allocation_state"] = "DROPPED"
    order["fulfillment_state"] = "CANCELLED"
    touch(order, bumped)
    cycle = store.cycles.get(order["allocation_cycle_id"])
    if cycle is not None:
        if calc.recompute_cycle(cycle):
            touch(cycle, bumped)
        promotion_sweep(cycle, bumped)
    if order["buyer_type"] == "RETAIL_ACCOUNT":
        acct = store.retail_accounts.get(order["retail_account_id"])
        if acct is not None and calc.recompute_credit(acct):
            touch(acct, bumped)


def _pick(order, bumped):
    if order["fulfillment_state"] != "PENDING" or order["allocation_state"] != "ALLOCATED":
        err("ERR_INVALID_TRANSITION", "PICK requires fulfillment PENDING and allocation ALLOCATED")
    order["fulfillment_state"] = "PICKED"
    touch(order, bumped)


def _ship(order, bumped):
    if order["fulfillment_state"] != "PICKED":
        err("ERR_INVALID_TRANSITION", "SHIP requires fulfillment PICKED")
    if order["delivery_mode"] == "HOME_DELIVERY":
        err("ERR_USE_APPOINTMENT_FLOW", "HOME_DELIVERY orders ship via the appointment flow")
    order["fulfillment_state"] = "SHIPPED"
    touch(order, bumped)


def _deliver(order, bumped):
    if order["fulfillment_state"] != "SHIPPED":
        err("ERR_INVALID_TRANSITION", "DELIVER requires fulfillment SHIPPED")
    if order["delivery_mode"] == "HOME_DELIVERY":
        err("ERR_USE_APPOINTMENT_FLOW", "HOME_DELIVERY orders deliver via the appointment flow")
    deliver_order(order, bumped)
