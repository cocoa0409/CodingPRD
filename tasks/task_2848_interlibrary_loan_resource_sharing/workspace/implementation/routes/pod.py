"""Purchase on demand (PRD 3.8)."""
from flask import Blueprint

from db import base_row, db, now, touch
from errors import ApiError
from middleware import (ACQUISITIONS, ADMIN, ILL_STAFF, auth, get_pod_order,
                        get_request)
from response import ok_row
from services import derive
from validate import body, opt_str, req_enum, req_str

bp = Blueprint("pod", __name__)

DECISIONS = ("APPROVE", "REJECT")
BLOCKING_HOLDINGS = ("HELD_AVAILABLE", "ON_ORDER")


def open_order(req, vendor, escalated_by_user_id):
    """Open a PROPOSED purchase proposal for a request (also used by the sweep)."""
    bib = db.bib_items.get(req["bib_item_id"]) or {}
    row = base_row()
    row.update({
        "request_id": req["id"],
        "list_price_cents": bib.get("list_price_cents"),
        "vendor": vendor,
        "escalated_by_user_id": escalated_by_user_id,
        "decided_by_user_id": None,
        "decision_note": None,
        "status": "PROPOSED",
        "decided_at": None,
        "received_at": None,
    })
    db.pod_orders[row["id"]] = row
    req["status"] = "ESCALATED_POD"
    touch(req)
    return row


@bp.route("/ill/requests/<request_id>/escalate", methods=["POST"])
def escalate_request(request_id):
    user_id, role = auth(ILL_STAFF)
    req = get_request(request_id)
    data = body()
    vendor = req_str(data, "vendor")
    # rung 40
    if req["status"] != "SOURCING":
        raise ApiError("ERR_REQUEST_INVALID_STATE")
    # rung 77
    bib = db.bib_items.get(req["bib_item_id"]) or {}
    if bib.get("local_holding_status") in BLOCKING_HOLDINGS:
        raise ApiError("ERR_ALREADY_HELD_LOCALLY")
    row = open_order(req, vendor, user_id)
    return ok_row(row, 201)


@bp.route("/ill/pod-orders/<order_id>/decision", methods=["POST"])
def decide_order(order_id):
    user_id, role = auth(ACQUISITIONS)
    order = get_pod_order(order_id)
    # rung 28: the ladder puts segregation of duties ahead of body shape and state
    if user_id == order["escalated_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    decision_note = opt_str(data, "decision_note")
    # rung 45
    if order["status"] != "PROPOSED":
        raise ApiError("ERR_POD_ORDER_INVALID_STATE")
    req = db.requests[order["request_id"]]
    bib = db.bib_items.get(req["bib_item_id"])
    if decision == "APPROVE":
        # rung 77: PRD 3.8 refuses an approval only once the work is on the shelf
        if bib is not None and bib["local_holding_status"] == "HELD_AVAILABLE":
            raise ApiError("ERR_ALREADY_HELD_LOCALLY")
        order["status"] = "APPROVED"
        order["decided_by_user_id"] = user_id
        order["decision_note"] = decision_note
        order["decided_at"] = now()
        touch(order)
        if bib is not None:
            bib["local_holding_status"] = "ON_ORDER"
            touch(bib)
        derive.notify(req, "POD_APPROVED",
                      "Purchase approved: %s" % (bib or {}).get("title", ""))
    else:
        order["status"] = "REJECTED"
        order["decided_by_user_id"] = user_id
        order["decision_note"] = decision_note
        order["decided_at"] = now()
        touch(order)
        # second cycle: the request walks the rota again on a fresh budget
        req["status"] = "SOURCING"
        req["attempt_count"] = 0
        req["unfilled_reason"] = "NONE"
        touch(req)
    return ok_row(order)


@bp.route("/ill/pod-orders/<order_id>/receive", methods=["POST"])
def receive_order(order_id):
    auth(ACQUISITIONS)
    order = get_pod_order(order_id)
    # rung 45
    if order["status"] != "APPROVED":
        raise ApiError("ERR_POD_ORDER_INVALID_STATE")
    req = db.requests[order["request_id"]]
    bib = db.bib_items.get(req["bib_item_id"])
    order["status"] = "RECEIVED"
    order["received_at"] = now()
    touch(order)
    if bib is not None:
        bib["local_holding_status"] = "HELD_AVAILABLE"
        touch(bib)
    req["status"] = "FILLED_BY_PURCHASE"
    req["closed_at"] = now()
    touch(req)
    derive.notify(req, "PURCHASE_RECEIVED",
                  "Purchased copy received: %s" % (bib or {}).get("title", ""))
    derive.recompute_patron_for_request(req, ("open_request_count",))
    return ok_row(order)


@bp.route("/ill/pod-orders/<order_id>", methods=["GET"])
def get_one_order(order_id):
    auth(ILL_STAFF, ACQUISITIONS, ADMIN)
    order = get_pod_order(order_id)
    return ok_row(order)
