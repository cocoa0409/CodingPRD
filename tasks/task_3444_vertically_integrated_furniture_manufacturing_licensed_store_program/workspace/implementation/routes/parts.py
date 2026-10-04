"""Parts orders (PRD §3.7): QUEUED -> SHIPPED -> DELIVERED with claim bubble-up."""
from flask import Blueprint, request

from constants import PARTS_STATUSES
from db import store
from errors import err
from middleware import auth, require_role
from util import (
    get_body, now_dt, ok_list, ok_object, paginate, req_enum, serialize, touch,
)

bp = Blueprint("parts", __name__)

_PARTS_NEXT = {"QUEUED": "SHIPPED", "SHIPPED": "DELIVERED"}


def get_parts_order(pid):
    p = store.parts_orders.get(pid)
    if p is None:
        err("ERR_PARTS_ORDER_NOT_FOUND", "unknown parts order id")
    return p


@bp.route("/api/parts-orders/<pid>", methods=["GET"])
def fetch_parts_order(pid):
    auth()
    return ok_object(serialize(get_parts_order(pid)), 200)


@bp.route("/api/parts-orders", methods=["GET"])
def list_parts_orders():
    auth()
    items = list(store.parts_orders.values())
    for field in ("claim_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [p for p in items if p[field] == value]
    page, pagination = paginate(items)
    return ok_list([serialize(p) for p in page], pagination)


@bp.route("/api/parts-orders/<pid>/transition", methods=["POST"])
def transition_parts_order(pid):
    _uid, role = auth()
    data = get_body()
    to_state = req_enum(data, "to_state", PARTS_STATUSES)
    require_role(role, ["LogisticsCoordinator"])
    part = get_parts_order(pid)
    if _PARTS_NEXT.get(part["status"]) != to_state:
        err("ERR_INVALID_TRANSITION", "parts order cannot move %s -> %s" % (part["status"], to_state))
    bumped = set()
    part["status"] = to_state
    touch(part, bumped)
    if to_state == "DELIVERED":
        claim = store.claims.get(part["claim_id"])
        if claim is not None and claim["status"] == "PARTS_ORDERED":
            siblings = [p for p in store.parts_orders.values() if p["claim_id"] == claim["id"]]
            if all(p["status"] == "DELIVERED" for p in siblings):
                # Bubble-up: the claim's last outstanding parts order has landed.
                claim["status"] = "RESOLVED"
                claim["resolved_at"] = now_dt()
                touch(claim, bumped)
    return ok_object(serialize(part), 200)
