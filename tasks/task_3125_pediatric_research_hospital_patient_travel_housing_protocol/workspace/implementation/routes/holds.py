"""Protocol hold endpoints and the freeze cascade (PRD §2.12, §3.9)."""

from flask import Blueprint

from db import DB, new_row, now_iso, touch
from errors import ApiError
from http_util import body_json, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    get_or_404, recompute_protocol_derived, revert_accepted_referrals,
    serialize_hold,
)

bp = Blueprint("holds", __name__)

VALID_HOLD_REASONS = {"IRB_REVIEW", "SAFETY_SIGNAL", "FUNDING_REVIEW", "SPONSOR_AUDIT"}


@bp.post("/programs/clinical-protocols/<protocol_id>/holds")
def create_hold(protocol_id):
    require_role("IRBReviewer")
    protocol = get_or_404("protocols", protocol_id)
    data = body_json()
    hold_reason = required(data, "hold_reason", "str")
    if hold_reason not in VALID_HOLD_REASONS:
        raise ApiError("ERR_INVALID_REQUEST")
    initiated_at = required(data, "initiated_at", "datetime")

    # PRD §3.9: raising a hold freezes a live protocol, so the host protocol must
    # be admitting work — OPEN, or already HELD where a second hold may stack
    # (§3.9's "no other ACTIVE hold remains" release rule). A DRAFT protocol
    # admits nobody and a CLOSED one is done: both report ERR_PROTOCOL_NOT_OPEN
    # (HTTP 409) and no hold row is written.
    if protocol["status"] not in ("OPEN", "HELD"):
        raise ApiError("ERR_PROTOCOL_NOT_OPEN")

    hold = new_row({
        "protocol_id": protocol["id"],
        "protocol_version": protocol["version"],
        "hold_reason": hold_reason,
        "initiated_at": initiated_at,
        "released_at": None,
        "status": "ACTIVE",
        "is_review_lock": False,
    })
    DB["holds"][hold["id"]] = hold

    # The protocol moves to HELD and every ACCEPTED referral reverts to SUBMITTED.
    protocol["status"] = "HELD"
    protocol["is_protocol_held"] = True
    revert_accepted_referrals(protocol)
    recompute_protocol_derived(protocol)
    touch(protocol)
    hold["protocol_version"] = protocol["version"]
    return success_object(serialize_hold(hold), 201)


@bp.post("/programs/protocol-holds/<hold_id>/release")
def release_hold(hold_id):
    require_role("ProtocolCoordinator")
    hold = get_or_404("holds", hold_id)
    protocol = get_or_404("protocols", hold["protocol_id"])
    if hold["status"] != "ACTIVE":
        raise ApiError("ERR_HOLD_NOT_ACTIVE")
    if protocol["status"] != "HELD":
        raise ApiError("ERR_PROTOCOL_NOT_HELD")

    hold["status"] = "RELEASED"
    hold["released_at"] = now_iso()
    hold["protocol_version"] = protocol["version"]
    touch(hold)

    remaining = [h for h in DB["holds"].values()
                 if h["protocol_id"] == protocol["id"] and h["status"] == "ACTIVE"]
    if remaining:
        protocol["is_protocol_held"] = True
    else:
        protocol["is_protocol_held"] = False
        protocol["status"] = "OPEN"
    recompute_protocol_derived(protocol)
    touch(protocol)
    hold["protocol_version"] = protocol["version"]
    return success_object(serialize_hold(hold), 200)


@bp.post("/programs/protocol-holds/<hold_id>/escalate")
def escalate_hold(hold_id):
    require_role("IRBReviewer")
    hold = get_or_404("holds", hold_id)
    protocol = get_or_404("protocols", hold["protocol_id"])
    if hold["status"] != "ACTIVE":
        raise ApiError("ERR_HOLD_NOT_ACTIVE")
    if hold["hold_reason"] != "IRB_REVIEW":
        raise ApiError("ERR_HOLD_NOT_IRB_REVIEW")

    hold["status"] = "ESCALATED"
    hold["protocol_version"] = protocol["version"]
    touch(hold)
    protocol["is_protocol_held"] = True
    touch(protocol)
    hold["protocol_version"] = protocol["version"]
    return success_object(serialize_hold(hold), 200)


@bp.get("/programs/protocol-holds")
def list_holds():
    require_role("Any")
    protocol_id = arg("protocol_id")
    status = arg("status")
    rows = ordered(DB["holds"].values())
    rows = filtered(rows, protocol_id=protocol_id, status=status)
    return list_response(rows, serialize_hold)