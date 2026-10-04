"""Customers and sales orders: registration, order placement with the
synchronous allocation sweep, and the fulfill / release / cancel transitions
with ship-date repricing."""

from flask import Blueprint, request

from db import STORE, get_clock
from domain import bump, make_customer, make_sales_order, ser_customer, ser_sales_order
from engine import sweep_and_bump, unit_price_cents
from util import (
    ALL_ROLES,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_ORDER_STATE,
    ERR_INVALID_REQUEST,
    ERR_LOT_NOT_DISTRIBUTABLE,
    auth_context,
    body,
    fail,
    get_path,
    get_ref,
    list_page,
    ok_object,
    require_role,
    require_target_role,
    v_enum,
    v_int,
    v_str,
)

bp = Blueprint("sales", __name__)

TIERS = ["FEDERAL", "ACCREDITED_LAB", "GENERAL"]
ORDER_STATES = ["PLACED", "ALLOCATED", "BACKORDERED", "FULFILLED", "CANCELLED"]
ORDER_TARGET_ROLES = {
    "FULFILLED": ["InventoryManager"],
    "BACKORDERED": ["InventoryManager", "Customer"],
    "CANCELLED": ["InventoryManager", "Customer"],
}


@bp.route("/metrology/customers", methods=["POST"])
def create_customer():
    _uid, role = auth_context()
    require_role(role, ["ProgramAdmin"])
    b = body()
    data = {
        "name": v_str(b, "name"),
        "tier": v_enum(b, "tier", TIERS),
        "credit_limit_cents": v_int(b, "credit_limit_cents", minv=0),
    }
    rec = make_customer(data)
    STORE["customers"][rec["id"]] = rec
    return ok_object(ser_customer(rec), 201)


def _resolve_order_customer(b, uid, role):
    """customer_id: optional for Customer (defaults to X-User-ID), required
    for InventoryManager."""
    if role == "Customer":
        cid = b.get("customer_id")
        if cid is None:
            cid = uid
        elif not isinstance(cid, str) or cid == "":
            fail(ERR_INVALID_REQUEST, 400, "customer_id must be a string")
    else:  # InventoryManager
        cid = v_str(b, "customer_id")
    return get_ref(STORE["customers"], cid, "customer")


@bp.route("/metrology/sales-orders", methods=["POST"])
def create_sales_order():
    uid, role = auth_context()
    require_role(role, ["Customer", "InventoryManager"])
    b = body()
    lot_id = v_str(b, "lot_id")
    quantity = v_int(b, "quantity", minv=1)
    lot = get_ref(STORE["lots"], lot_id, "material lot")
    customer = _resolve_order_customer(b, uid, role)
    if lot["status"] != "IN_DISTRIBUTION":
        fail(
            ERR_LOT_NOT_DISTRIBUTABLE,
            409,
            "the lot is not in distribution",
        )
    if customer["credit_hold"]:
        fail(
            ERR_CREDIT_LIMIT_EXCEEDED,
            402,
            "customer is under a credit hold",
        )
    program = STORE["programs"].get(lot["program_id"])
    quoted = unit_price_cents(program, customer["tier"])
    order = make_sales_order(lot["id"], customer["id"], quantity, quoted)
    STORE["sales_orders"][order["id"]] = order
    # synchronous allocation sweep; the new order is itself a candidate and
    # keeps its creation version (the sweep outcome is its birth state)
    _mutated, reserved_changed = sweep_and_bump(
        lot, include=order, include_is_new=True
    )
    if reserved_changed:
        bump(lot)
    if order["status"] == "PLACED":
        order["status"] = "BACKORDERED"
    return ok_object(ser_sales_order(order), 201)


@bp.route("/metrology/sales-orders/<oid>", methods=["GET"])
def get_sales_order(oid):
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    order = get_path(STORE["sales_orders"], oid, "sales order")
    return ok_object(ser_sales_order(order), 200)


@bp.route("/metrology/sales-orders", methods=["GET"])
def list_sales_orders():
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    lot_id = request.args.get("lot_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(STORE["sales_orders"].values())
    if lot_id is not None:
        items = [o for o in items if o["lot_id"] == lot_id]
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_page(items, ser_sales_order)


@bp.route("/metrology/sales-orders/<oid>/transitions", methods=["POST"])
def sales_order_transition(oid):
    uid, role = auth_context()
    require_role(role, ["InventoryManager", "Customer"])
    b = body()
    require_target_role(role, b.get("to"), ORDER_TARGET_ROLES)
    to = v_enum(b, "to", ORDER_STATES)
    order = get_path(STORE["sales_orders"], oid, "sales order")

    # ownership (stage 4.6): a Customer may only act on their own order
    if role == "Customer" and order["customer_id"] != uid:
        fail(ERR_FORBIDDEN_OWNERSHIP, 403, "the order belongs to another customer")

    lot = STORE["lots"].get(order["lot_id"])

    if to == "FULFILLED":
        if order["status"] != "ALLOCATED":
            fail(
                ERR_INVALID_ORDER_STATE,
                409,
                "only an ALLOCATED order may be fulfilled",
            )
        program = STORE["programs"].get(lot["program_id"]) if lot else None
        customer = STORE["customers"].get(order["customer_id"])
        final_price = unit_price_cents(program, customer["tier"])
        subtotal = order["allocated_quantity"] * final_price
        fee = (
            program["handling_fee_flat_cents"]
            if subtotal < program["handling_fee_threshold_cents"]
            else 0
        )
        order["final_unit_price_cents"] = final_price
        order["invoice_subtotal_cents"] = subtotal
        order["handling_fee_cents"] = fee
        order["invoice_total_cents"] = subtotal + fee
        order["fulfilled_at"] = get_clock()
        order["status"] = "FULFILLED"
        if lot is not None:
            lot["units_reserved"] -= order["allocated_quantity"]
            lot["units_shipped"] += order["allocated_quantity"]
            bump(lot)
        bump(order)
        return ok_object(ser_sales_order(order), 200)

    if to == "BACKORDERED":
        # release
        if order["status"] != "ALLOCATED":
            fail(
                ERR_INVALID_ORDER_STATE,
                409,
                "only an ALLOCATED order may be released",
            )
        if lot is not None:
            lot["units_reserved"] -= order["allocated_quantity"]
        order["allocated_quantity"] = 0
        order["status"] = "BACKORDERED"
        # the release-triggered sweep excludes the released order itself
        if lot is not None:
            sweep_and_bump(lot, exclude_id=order["id"])
            bump(lot)
        bump(order)
        return ok_object(ser_sales_order(order), 200)
    if to == "CANCELLED":
        if order["status"] not in ("PLACED", "ALLOCATED", "BACKORDERED"):
            fail(
                ERR_INVALID_ORDER_STATE,
                409,
                "order status {} does not permit cancellation".format(
                    order["status"]
                ),
            )
        if lot is not None:
            lot["units_reserved"] -= order["allocated_quantity"]
        order["allocated_quantity"] = 0
        order["status"] = "CANCELLED"
        if lot is not None:
            sweep_and_bump(lot)
            bump(lot)
        bump(order)
        return ok_object(ser_sales_order(order), 200)

    fail(
        ERR_INVALID_ORDER_STATE,
        409,
        "no declared order transition from {} to {}".format(order["status"], to),
    )
