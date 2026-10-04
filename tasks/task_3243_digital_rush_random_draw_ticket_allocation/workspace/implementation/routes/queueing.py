"""The rush queue: joining and listing positions in rank order."""

from flask import Blueprint, request

from clock import CLOCK
from db import DB
from errors import ApiError
from response import apply_filters, ok, ok_list, public, public_list
from routes import actor, pagination, payload
import guards_helpers

bp = Blueprint("queueing", __name__)


@bp.post("/performances/<performance_id>/queue-positions")
def join_queue(performance_id):
    """Join the rush queue once the release instant has passed."""
    user_id, _role = actor(["Patron"])
    body = payload()
    performance = DB.get("performance", performance_id)
    if performance is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND")

    allocation = DB.get("allocation", body.get("allocation_id"))
    if allocation is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if allocation["performance_id"] != performance_id:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    patron = DB.get("patron", user_id)
    if patron is None:
        raise ApiError("ERR_PATRON_NOT_FOUND")

    guards_helpers.require_released_allocation(allocation, performance)

    if patron["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    if performance["status"] != "ONSALE":
        raise ApiError("ERR_INVALID_STATE")

    for existing in DB.all("queue_position"):
        if existing["performance_id"] != performance_id:
            continue
        if existing["patron_id"] != user_id:
            continue
        if existing["status"] in ("WAITING", "ADMITTED"):
            raise ApiError("ERR_QUEUE_POSITION_EXISTS")

    joined_at = CLOCK.stamp()
    position = {
        "performance_id": performance_id,
        "allocation_id": allocation["id"],
        "patron_id": user_id,
        "status": "WAITING",
        "joined_at": joined_at,
        "admit_at": None,
        "admit_expires_at": None,
        "rank_position": None,
    }
    DB.insert("queue_position", position)
    rank_queue(performance_id)
    return ok(public(position), 201)


def rank_queue(performance_id):
    """The performance's queue in rank order; joined_at decides placement."""
    active = [
        q
        for q in DB.all("queue_position")
        if q["performance_id"] == performance_id
        and q["status"] in ("WAITING", "ADMITTED")
    ]
    active.sort(key=lambda q: (q.get("joined_at") or "", q.get("created_at") or ""))
    for index, position in enumerate(active):
        position["rank_position"] = index + 1
    return active


@bp.get("/performances/<performance_id>/queue-positions")
def list_queue(performance_id):
    actor(
        ["OpsManager", "AllocationsCoordinator", "CustomerService", "Patron", "ConciergeDeskStaff"]
    )
    performance = DB.get("performance", performance_id)
    if performance is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND")
    limit, offset = pagination()
    rows = [q for q in DB.all("queue_position") if q["performance_id"] == performance_id]
    rows = apply_filters(rows, request.args, ("patron_id", "status"))
    rows.sort(key=lambda q: (q.get("joined_at") or "", q.get("created_at") or ""))
    return ok_list(public_list(rows), limit, offset)