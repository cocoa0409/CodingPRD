"""Concierge desk handoff: token verification and failed-attempt recording."""

from flask import Blueprint

from clock import CLOCK
from db import DB
from errors import ApiError
from response import ok, public
from routes import actor, payload
from services import engine

bp = Blueprint("handoffs", __name__)


@bp.post("/handoffs")
def record_handoff():
    """Verify a presented token at an open desk with capacity left."""
    _user_id, _role = actor(["ConciergeDeskStaff"])
    body = payload()
    purchase = DB.get("purchase", body.get("purchase_id"))
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")

    idempotency_key = body.get("idempotency_key")
    if idempotency_key is not None and purchase.get("last_handoff_key") == idempotency_key:
        return ok(public(purchase), 201)

    desk_code = body.get("desk_code")
    desk = None
    for candidate in DB.all("desk"):
        if candidate["desk_code"] == desk_code:
            desk = candidate
            break
    if desk is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    if purchase.get("handoff_failed_at") is not None:
        raise ApiError("ERR_HANDOFF_TOKEN_INVALID")
    if purchase["handoff_status"] != "PENDING_CONCIERGE":
        raise ApiError("ERR_INVALID_STATE")

    if desk["status"] != "OPEN" or int(desk["handoffs_today"]) >= int(desk["daily_capacity"]):
        raise ApiError("ERR_DESK_CAPACITY_REACHED")

    submitted = body.get("redemption_code")
    if submitted is None or str(submitted) != str(purchase.get("handoff_token")):
        purchase["handoff_status"] = "FAILED"
        purchase["handoff_failed_at"] = CLOCK.stamp()
        purchase["last_handoff_key"] = idempotency_key
        DB.touch("purchase", purchase)
        DB.touch("desk", desk)
        raise ApiError("ERR_HANDOFF_TOKEN_INVALID")

    purchase["handoff_status"] = "VERIFIED"
    purchase["handoff_verified_at"] = CLOCK.stamp()
    purchase["logistics_status"] = "COLLECTED"
    purchase["last_handoff_key"] = idempotency_key
    desk["handoffs_today"] = int(desk["handoffs_today"]) + 1
    engine.saturate_desk_if_full(desk)
    DB.touch("desk", desk)
    return ok(public(DB.touch("purchase", purchase)), 201)