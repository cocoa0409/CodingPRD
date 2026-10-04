"""Order endpoints: create, read, list, submit, ship, cancel (PRD 3.6)."""
import uuid
from decimal import Decimal

from flask import Blueprint, request

import db as dbmod
import domain as D
from errors import ApiError
from middleware import authenticate, forbid, get_body
from response import paginate, success
from util import is_int, round_half_up

bp = Blueprint("orders", __name__)

_READ_ROLES = {"LabProcurement", "AccountManager", "SupplyOps", "PlatformAdmin"}
_WRITE_ROLES = {"LabProcurement", "AccountManager", "PlatformAdmin"}


@bp.post("/lab/orders")
def create_order():
    uid, role = authenticate(_WRITE_ROLES)
    body = get_body()
    account_id = body.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "account_id is required")
    if role == "LabProcurement" and account_id != uid:
        forbid("LabProcurement may act only on its own account")
    acct = dbmod.store.accounts.get(account_id)
    if acct is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "Account not found")
    lines = body.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "lines must be a non-empty array"
        )
    norm_lines = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "each line must be an object")
        sku = ln.get("sku")
        if not isinstance(sku, str) or not sku:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "each line requires a sku string"
            )
        norm_lines.append({"sku": sku, "quantity": ln.get("quantity")})
    # Existence of referenced skus (priority 3) precedes quantity checks (priority 7).
    for ln in norm_lines:
        if ln["sku"] not in dbmod.store.catalog_by_sku:
            raise ApiError(
                "ERR_CATALOG_ITEM_NOT_FOUND", 404,
                "An order line references a sku not present in the catalog",
            )
    for ln in norm_lines:
        q = ln["quantity"]
        if not is_int(q) or q <= 0:
            raise ApiError(
                "ERR_INVALID_QUANTITY", 400,
                "Order line quantity must be a positive integer",
            )
    now = dbmod.now()
    order = {
        "id": str(uuid.uuid4()),
        "account_id": account_id,
        "lines": norm_lines,
        "status": "DRAFT",
        "shipping_class": None,
        "handling_fee_cents": 0,
        "discount_pct": 0,
        "goods_subtotal_cents": 0,
        "total_cents": 0,
        "total_quantity": 0,
        "allocation_score": None,
        "submitted_at": None,
        "shipped_at": None,
        "delivered_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": dbmod.store.next_seq(),
    }
    with dbmod.store.lock:
        dbmod.store.orders[order["id"]] = order
    return success(D.order_json(order), code=201)


@bp.get("/lab/orders/<order_id>")
def get_order(order_id):
    uid, role = authenticate(_READ_ROLES)
    order = dbmod.store.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Order not found")
    if role == "LabProcurement" and order["account_id"] != uid:
        forbid("LabProcurement may read only its own account's orders")
    return success(D.order_json(order))


@bp.get("/lab/orders")
def list_orders():
    uid, role = authenticate(_READ_ROLES)
    items = list(dbmod.store.orders.values())
    if role == "LabProcurement":
        items = [o for o in items if o["account_id"] == uid]
    f_account = request.args.get("account_id")
    if f_account is not None:
        items = [o for o in items if o["account_id"] == f_account]
    f_status = request.args.get("status")
    if f_status is not None:
        items = [o for o in items if o["status"] == f_status]
    items = D.created_sorted(items)
    page, meta = paginate(items)
    return success(
        [D.order_json(o) for o in page], response_type="array", pagination=meta
    )


@bp.post("/lab/orders/<order_id>/submit")
def submit_order(order_id):
    uid, role = authenticate(_WRITE_ROLES)
    order = dbmod.store.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Order not found")
    if role == "LabProcurement" and order["account_id"] != uid:
        forbid("LabProcurement may act only on its own account's orders")
    # Priority 4: state guards.
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT order can be submitted")
    acct = dbmod.store.accounts[order["account_id"]]
    if acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account is not ACTIVE")
    items = D.order_items(order)
    # Priority 6: controlled-substance license gate.
    if any(item["item_class"] == "CONTROLLED" for item, _q in items) and not acct[
        "controlled_substance_license"
    ]:
        raise ApiError(
            "ERR_CONTROLLED_LICENSE_REQUIRED", 422,
            "Order contains a CONTROLLED item but the account holds no license",
        )
    # Priority 8: credit gate, evaluated last.
    if acct["credit_status"] != "GOOD":
        raise ApiError("ERR_CREDIT_HOLD", 402, "Account is on credit hold")
    now = dbmod.now()
    # Pricing snapshot (calculations.order_total_pricing), frozen at submit.
    agr = D.live_agreement_for_account(order["account_id"], now)
    if agr is not None:
        tier = D.ea_tier_for_trailing(D.account_trailing_spend(order["account_id"], now))
        discount_pct = D.EA_TIER_DISCOUNT[tier]
    else:
        tier = "BASE"
        discount_pct = 0
    goods_subtotal = 0
    for item, qty in items:
        line_net = round_half_up(
            Decimal(item["base_price_cents"]) * qty * (100 - discount_pct) / 100
        )
        goods_subtotal += line_net
    shipping_class = max(
        (item["item_class"] for item, _q in items),
        key=lambda c: D.CLASS_PRECEDENCE[c],
    )
    handling_fee = D.HANDLING_FEE[shipping_class]
    total_cents = goods_subtotal + handling_fee
    total_quantity = sum(q for _i, q in items)
    surge_groups = D.active_surge_groups()
    surge_affected = any(item["allocation_group"] in surge_groups for item, _q in items)
    satisfiable = all(
        item["stock_on_hand"] - item["reserved_quantity"] >= qty for item, qty in items
    )
    with dbmod.store.lock:
        order["discount_pct"] = discount_pct
        order["goods_subtotal_cents"] = goods_subtotal
        order["shipping_class"] = shipping_class
        order["handling_fee_cents"] = handling_fee
        order["total_cents"] = total_cents
        order["total_quantity"] = total_quantity
        order["submitted_at"] = now
        if not surge_affected and satisfiable:
            order["status"] = "ALLOCATED"
            order["allocation_score"] = None
            for item, qty in items:
                item["reserved_quantity"] += qty
        else:
            order["status"] = "BACKORDERED"
            order["allocation_score"] = (
                D.PRIORITY_WEIGHT[acct["priority_class"]] * D.TIER_MULT[tier]
            )
        order["version"] += 1
        order["updated_at"] = now
    return success(D.order_json(order))


@bp.post("/lab/orders/<order_id>/ship")
def ship_order(order_id):
    authenticate({"SupplyOps", "PlatformAdmin"})
    order = dbmod.store.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Order not found")
    if order["status"] != "ALLOCATED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an ALLOCATED order can be shipped"
        )
    now = dbmod.now()
    acct = dbmod.store.accounts[order["account_id"]]
    with dbmod.store.lock:
        for item, qty in D.order_items(order):
            item["stock_on_hand"] -= qty
            item["reserved_quantity"] -= qty
        order["status"] = "SHIPPED"
        order["shipped_at"] = now
        order["version"] += 1
        order["updated_at"] = now
        D.post_charge(acct, order["total_cents"], now)
    return success(D.order_json(order))


@bp.post("/lab/orders/<order_id>/cancel")
def cancel_order(order_id):
    uid, role = authenticate(_WRITE_ROLES)
    order = dbmod.store.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Order not found")
    if role == "LabProcurement" and order["account_id"] != uid:
        forbid("LabProcurement may act only on its own account's orders")
    if order["status"] in ("SHIPPED", "DELIVERED", "CANCELLED"):
        raise ApiError(
            "ERR_ORDER_NOT_CANCELLABLE", 409,
            "A SHIPPED, DELIVERED, or CANCELLED order cannot be cancelled",
        )
    now = dbmod.now()
    with dbmod.store.lock:
        if order["status"] == "ALLOCATED":
            for item, qty in D.order_items(order):
                item["reserved_quantity"] -= qty
        order["status"] = "CANCELLED"
        order["version"] += 1
        order["updated_at"] = now
    return success(D.order_json(order))
