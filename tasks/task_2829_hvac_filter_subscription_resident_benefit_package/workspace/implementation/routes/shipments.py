"""Fulfilment: dispatch, delivery and the return fork (PRD 3.5)."""
from flask import Blueprint

import calc
import clock
import envelope
import guards
import ledger
import validate
import views
from errors import fail
from store import db, sorted_rows, touch

bp = Blueprint("shipments", __name__)

SHIPMENT_STATUSES = ("SCHEDULED", "SHIPPED", "DELIVERED", "RETURN_REQUESTED",
                     "RETURNED", "UNRETURNED_WRITTEN_OFF", "CANCELLED")


def _owner_subscription(uid, role, shipment):
    sub = db.subscriptions[shipment["subscription_id"]]
    guards.own_subscription(uid, role, sub)
    return sub


@bp.get("/shipments/<shipment_id>")
def read_shipment(shipment_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager", "Resident"])
    rec = guards.get_shipment(shipment_id)
    _owner_subscription(uid, role, rec)
    return envelope.object_response(views.shipment_view(rec))


@bp.get("/shipments")
def list_shipments():
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    limit, offset, filters = guards.pagination({"status": SHIPMENT_STATUSES},
                                               ("subscription_id", "sku_id"))
    rows = [s for s in db.shipments.values()
            if all(s[k] == v for k, v in filters.items())]
    if role == "PropertyManager":
        rows = [s for s in rows
                if db.subscriptions[s["subscription_id"]]["property_id"] == uid]
    rows = sorted_rows(rows)
    return envelope.list_response([views.shipment_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))


@bp.post("/shipments/<shipment_id>/ship")
def ship(shipment_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_shipment(shipment_id)
    body = validate.json_body()
    tracking_code = validate.req_string(body, "tracking_code")
    sub = db.subscriptions[rec["subscription_id"]]
    if rec["status"] != "SCHEDULED":
        fail("ERR_SHIPMENT_STATE_INVALID", "the shipment is not SCHEDULED")
    if sub["status"] != "ACTIVE":
        fail("ERR_SHIPMENT_STATE_INVALID",
             "the owning subscription is not ACTIVE")

    rec["tracking_code"] = tracking_code
    rec["shipped_at"] = clock.now_iso()
    rec["status"] = "SHIPPED"
    touch(rec)
    return envelope.object_response(views.shipment_view(rec))


@bp.post("/shipments/<shipment_id>/deliver")
def deliver(shipment_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_shipment(shipment_id)
    body = validate.json_body()
    delivered_at = validate.req_instant(body, "delivered_at")
    # PRD 3.5 files the "not before shipped_at" comparison under shape
    # validation, so it runs ahead of the status rung.
    if rec["shipped_at"] is not None:
        if delivered_at < clock.parse_instant(rec["shipped_at"]):
            fail("ERR_INVALID_REQUEST",
                 "delivered_at must not precede shipped_at")
    if rec["status"] != "SHIPPED":
        fail("ERR_SHIPMENT_STATE_INVALID", "the shipment is not SHIPPED")

    rec["delivered_at"] = clock.fmt_instant(delivered_at)
    rec["status"] = "DELIVERED"
    touch(rec)
    return envelope.object_response(views.shipment_view(rec))


@bp.post("/shipments/<shipment_id>/request-return")
def request_return(shipment_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    rec = guards.get_shipment(shipment_id)
    _owner_subscription(uid, role, rec)
    body = validate.json_body()
    reason = validate.req_text(body, "return_reason")
    if rec["status"] != "DELIVERED":
        fail("ERR_SHIPMENT_STATE_INVALID", "the shipment is not DELIVERED")

    rec["_return_reason"] = reason
    rec["status"] = "RETURN_REQUESTED"
    touch(rec)
    return envelope.object_response(views.shipment_view(rec))


@bp.post("/shipments/<shipment_id>/return")
def return_shipment(shipment_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_shipment(shipment_id)
    body = validate.json_body()
    returned_at = validate.req_instant(body, "returned_at")
    if rec["delivered_at"] is not None:
        if returned_at < clock.parse_instant(rec["delivered_at"]):
            fail("ERR_INVALID_REQUEST",
                 "returned_at must not precede delivered_at")
    if rec["status"] != "RETURN_REQUESTED":
        fail("ERR_SHIPMENT_STATE_INVALID", "the shipment is not RETURN_REQUESTED")

    rec["returned_at"] = clock.fmt_instant(returned_at)
    rec["unreturned_fee_cents"] = 0
    rec["status"] = "RETURNED"
    touch(rec)
    return envelope.object_response(views.shipment_view(rec))


@bp.post("/shipments/<shipment_id>/write-off")
def write_off(shipment_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_shipment(shipment_id)
    if rec["status"] != "RETURN_REQUESTED":
        fail("ERR_SHIPMENT_STATE_INVALID", "the shipment is not RETURN_REQUESTED")

    sub = db.subscriptions[rec["subscription_id"]]
    fee = calc.unreturned_shipment_fee(rec)
    rec["unreturned_fee_cents"] = fee
    rec["status"] = "UNRETURNED_WRITTEN_OFF"
    touch(rec)
    ledger.post_one_off(sub, "UNRETURNED_SHIPMENT_FEE", fee,
                        "unreturned shipment write-off", rec["id"])
    return envelope.object_response(views.shipment_view(rec))
