"""Delivery endpoints (PRD SS3.5): ship, confirm, reject."""
from flask import Blueprint, request

import store
from domain import (lazy_lot, order_lines, reject_delivery_effects, touch,
                    training_compliant)
from errors import fail
from serializers import ser_delivery
from store import db
from util import (auth, body, list_response, new_id, ok, req_array, req_int,
                  req_str, sort_std)

bp = Blueprint("deliveries", __name__)

DELIVERY_READERS = ("BrandAdmin", "DistributorRep", "RetailManager", "SafetyOfficer")


def _get_delivery(did):
    d = db["deliveries"].get(did)
    if d is None:
        fail("ERR_NOT_FOUND", 404, "delivery not found")
    return d


@bp.post("/api/deliveries")
def create_delivery():
    _, uid = auth("DistributorRep")
    b = body()
    order_id = req_str(b, "order_id")
    account_id = req_str(b, "account_id")
    lines_in = req_array(b, "lines", non_empty=True)
    parsed = []
    for item in lines_in:
        if not isinstance(item, dict):
            fail("ERR_VALIDATION", 400, "each delivery line must be an object")
        lot_id = req_str(item, "lot_id")
        qty = req_int(item, "qty", min_value=1)
        parsed.append((lot_id, qty))
    # referenced-resource existence, left to right: order, account, then lots
    order = db["orders"].get(order_id)
    if order is None:
        fail("ERR_NOT_FOUND", 404, "order not found")
    # entity-backed ownership: the delivery's distributor is the order's
    if order["distributor_id"] != uid:
        fail("ERR_FORBIDDEN", 403, "X-User-ID must equal the order's distributor_id")
    account = db["accounts"].get(account_id)
    if account is None:
        fail("ERR_NOT_FOUND", 404, "account not found")
    lots = []
    for lot_id, _qty in parsed:
        lot = db["lots"].get(lot_id)
        if lot is None:
            fail("ERR_NOT_FOUND", 404, "lot not found")
        lots.append(lot)
    # state legality on the order's two dimensions
    if order["fulfillment_status"] in ("DELIVERED", "REJECTED"):
        fail("ERR_ALREADY_TERMINAL", 409, "order fulfillment is " + order["fulfillment_status"])
    if order["fulfillment_status"] != "UNSHIPPED":
        fail("ERR_INVALID_STATE", 409, "order has already shipped")
    if order["allocation_status"] == "CANCELLED":
        fail("ERR_ALREADY_TERMINAL", 409, "order is CANCELLED")
    if order["allocation_status"] not in ("ALLOCATED", "PARTIAL"):
        fail("ERR_INVALID_STATE", 409, "order allocation is not ALLOCATED or PARTIAL")
    # business safety: QUARANTINED / RECALLED lots are undeliverable
    for lot in lots:
        lazy_lot(lot)
        if lot["status"] in ("QUARANTINED", "RECALLED"):
            fail("ERR_LOT_NOT_DELIVERABLE", 422, "lot is " + lot["status"])
    # business constraint: every shipped product must be AUTHORIZED for the account
    for lot in lots:
        authorized = any(
            a["account_id"] == account_id and a["product_id"] == lot["product_id"]
            and a["status"] == "AUTHORIZED"
            for a in db["authorizations"].values())
        if not authorized:
            fail("ERR_PRODUCT_NOT_AUTHORIZED", 422,
                 "product " + lot["product_id"] + " is not authorized for the account")
    # business constraint: quantity / product membership / servicing
    order_product_ids = {l["product_id"] for l in order_lines(order_id)}
    per_lot_qty = {}
    for lot, qty in zip(lots, (q for _i, q in parsed)):
        if lot["product_id"] not in order_product_ids:
            fail("ERR_QUANTITY_MISMATCH", 422,
                 "lot product does not appear on the order")
        per_lot_qty[lot["id"]] = per_lot_qty.get(lot["id"], 0) + qty
    for lot_id, total in per_lot_qty.items():
        if total > db["lots"][lot_id]["allocated_units"]:
            fail("ERR_QUANTITY_MISMATCH", 422,
                 "delivery quantity exceeds the lot's allocated pool")
    if account["distributor_id"] != order["distributor_id"]:
        fail("ERR_QUANTITY_MISMATCH", 422,
             "account is not served by the order's distributor")
    # standing activity gates
    dist = db["distributors"].get(order["distributor_id"])
    if dist is None:
        fail("ERR_NOT_FOUND", 404, "distributor not found")
    if dist["status"] != "ACTIVE":
        fail("ERR_DISTRIBUTOR_NOT_ACTIVE", 409, "distributor is not ACTIVE")
    if account["approval_status"] != "APPROVED":
        fail("ERR_ACCOUNT_NOT_APPROVED", 409, "account is not APPROVED")
    # effects: per line, units move allocated -> delivered; order ships
    now = store.now()
    for lot, (_lot_id, qty) in zip(lots, parsed):
        lot["allocated_units"] -= qty
        lot["delivered_units"] += qty
    delivery = {
        "id": new_id(), "_seq": store.next_seq(), "order_id": order_id,
        "account_id": account_id, "distributor_id": order["distributor_id"],
        "lines": [{"lot_id": lot_id, "qty": qty} for lot_id, qty in parsed],
        "status": "PENDING", "confirmed_at": None,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["deliveries"][delivery["id"]] = delivery
    order["fulfillment_status"] = "IN_TRANSIT"
    touch(order)
    return ok(ser_delivery(delivery), 201)


@bp.get("/api/deliveries")
def list_deliveries():
    auth(*DELIVERY_READERS)
    items = sort_std(db["deliveries"].values())
    order_id = request.args.get("order_id")
    account_id = request.args.get("account_id")
    distributor_id = request.args.get("distributor_id")
    status = request.args.get("status")
    if order_id is not None:
        items = [d for d in items if d["order_id"] == order_id]
    if account_id is not None:
        items = [d for d in items if d["account_id"] == account_id]
    if distributor_id is not None:
        items = [d for d in items if d["distributor_id"] == distributor_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return list_response([ser_delivery(d) for d in items])


@bp.get("/api/deliveries/<did>")
def get_delivery(did):
    auth(*DELIVERY_READERS)
    return ok(ser_delivery(_get_delivery(did)))


@bp.post("/api/deliveries/<did>/confirm")
def confirm_delivery(did):
    _, uid = auth("RetailManager")
    d = _get_delivery(did)
    # entity-backed ownership: X-User-ID is the receiving account
    if d["account_id"] != uid:
        fail("ERR_FORBIDDEN", 403, "X-User-ID must equal the delivery's account_id")
    if d["status"] != "PENDING":
        fail("ERR_ALREADY_TERMINAL", 409, "delivery is " + d["status"])
    # business safety: every line lot must be unexpired (now strictly before expiry)
    now = store.now()
    for line in d["lines"]:
        lot = db["lots"][line["lot_id"]]
        if not now < lot["expires_at"]:
            fail("ERR_LOT_EXPIRED", 422, "a delivery line lot has expired")
    # business constraint: training coverage
    if not training_compliant(d["account_id"]):
        fail("ERR_TRAINING_INSUFFICIENT", 422,
             "fewer than 2 ACTIVE slicing-module or 2 ACTIVE allergen-module certifications")
    # business constraint: account still APPROVED
    account = db["accounts"].get(d["account_id"])
    if account is None or account["approval_status"] != "APPROVED":
        fail("ERR_ACCOUNT_NOT_APPROVED", 409, "account is not APPROVED")
    d["status"] = "CONFIRMED"
    d["confirmed_at"] = now
    touch(d)
    order = db["orders"].get(d["order_id"])
    if order is not None:
        order["fulfillment_status"] = "DELIVERED"
        touch(order)
    return ok(ser_delivery(d))


@bp.post("/api/deliveries/<did>/reject")
def reject_delivery_endpoint(did):
    _, uid = auth("RetailManager")
    d = _get_delivery(did)
    if d["account_id"] != uid:
        fail("ERR_FORBIDDEN", 403, "X-User-ID must equal the delivery's account_id")
    if d["status"] != "PENDING":
        fail("ERR_ALREADY_TERMINAL", 409, "delivery is " + d["status"])
    reject_delivery_effects(d)
    return ok(ser_delivery(d))
