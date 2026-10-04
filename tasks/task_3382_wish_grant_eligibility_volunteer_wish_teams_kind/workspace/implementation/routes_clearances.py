"""MedicalClearance request, list, and provider decisions with the
TRAVEL wish hold / lift cascades."""

from flask import Blueprint, request

from auth import require_roles
from db import STORE, now, new_entity, touch
from errors import ApiError
from resp import ok, created, list_resp
from serialize import ser_clearance
from util import (
    body_json, req_str, req_enum, req_field, opt_str, parse_date,
    pagination, paginate, bad,
)

bp = Blueprint("clearances", __name__)

_DECISIONS = {"CLEARED", "CONDITIONAL", "DENIED", "REVOKED"}
_ACTIVE_STATES = {"PENDING", "CLEARED", "CONDITIONAL"}
_REQUESTABLE_WISH_STATES = {
    "DETERMINED", "PLANNING", "PLAN_APPROVED",
    "READY_TO_SCHEDULE", "SCHEDULED", "MEDICAL_HOLD",
}


@bp.post("/wish-grant/medical-clearances")
@require_roles("WishCoordinator")
def request_clearance():
    body = body_json()
    wish_id = req_str(body, "wish_id")
    wish = STORE["wishes"].get(wish_id)
    if wish is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Wish not found")
    if wish["status"] not in _REQUESTABLE_WISH_STATES:
        raise ApiError(
            "ERR_INVALID_WISH_STATE", 409,
            "Wish %s does not accept a clearance request" % wish["status"],
        )
    if wish["wish_type"] != "TRAVEL":
        raise ApiError(
            "ERR_WISH_TYPE_NO_CLEARANCE", 422,
            "Medical clearance may only be requested for TRAVEL wishes",
        )
    for c in STORE["clearances"].values():
        if c["wish_id"] == wish["id"] and c["status"] in _ACTIVE_STATES:
            raise ApiError(
                "ERR_CLEARANCE_ALREADY_ACTIVE", 409,
                "The wish already has an active clearance",
            )
    c = new_entity(
        wish_id=wish["id"],
        status="PENDING",
        accommodations=[],
        valid_until=None,
        decision_note=None,
        decided_at=None,
    )
    STORE["clearances"][c["id"]] = c
    return created(ser_clearance(c))


@bp.get("/wish-grant/wishes/<wid>/medical-clearances")
@require_roles("WishCoordinator", "MedicalProvider", "ChapterDirector")
def list_clearances(wid):
    wish = STORE["wishes"].get(wid)
    if wish is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Wish not found")
    limit, offset = pagination()
    items = sorted(STORE["clearances"].values(), key=lambda e: e["created_at"])
    items = [c for c in items if c["wish_id"] == wid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total, has_more = paginate(items, limit, offset)
    return list_resp([ser_clearance(c) for c in page], total, limit, offset, has_more)


@bp.post("/wish-grant/medical-clearances/<cid>/decide")
@require_roles("MedicalProvider")
def decide_clearance(cid):
    c = STORE["clearances"].get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "MedicalClearance not found")
    body = body_json()
    decision = req_enum(body, "decision", _DECISIONS)
    valid_until = None
    accommodations = []
    if decision in ("CLEARED", "CONDITIONAL"):
        valid_until = parse_date(req_field(body, "valid_until"), "valid_until")
    if decision == "CONDITIONAL":
        acc = req_field(body, "accommodations")
        if (
            not isinstance(acc, list)
            or len(acc) == 0
            or any(not isinstance(a, str) for a in acc)
        ):
            bad("CONDITIONAL requires a non-empty accommodations array")
        accommodations = list(acc)
    decision_note = opt_str(body, "decision_note")

    if decision in ("CLEARED", "CONDITIONAL", "DENIED"):
        if c["status"] != "PENDING":
            raise ApiError(
                "ERR_INVALID_CLEARANCE_STATE", 409,
                "%s requires PENDING" % decision,
            )
    else:  # REVOKED
        if c["status"] not in ("CLEARED", "CONDITIONAL"):
            raise ApiError(
                "ERR_INVALID_CLEARANCE_STATE", 409,
                "REVOKED requires CLEARED or CONDITIONAL",
            )

    c["status"] = decision
    c["decided_at"] = now()
    if valid_until is not None:
        c["valid_until"] = valid_until
    if decision == "CONDITIONAL":
        c["accommodations"] = accommodations
    if decision_note is not None:
        c["decision_note"] = decision_note
    touch(c)

    wish = STORE["wishes"][c["wish_id"]]
    if decision in ("CLEARED", "CONDITIONAL"):
        # Travel gate re-evaluation (either/or, not chained).
        if wish["status"] == "PLAN_APPROVED":
            wish["status"] = "READY_TO_SCHEDULE"
            touch(wish)
        elif wish["status"] == "MEDICAL_HOLD":
            wish["status"] = wish["hold_return_state"]
            wish["hold_return_state"] = None
            touch(wish)
    elif decision == "REVOKED":
        if wish["status"] in ("PLAN_APPROVED", "READY_TO_SCHEDULE", "SCHEDULED"):
            wish["hold_return_state"] = (
                "PLAN_APPROVED"
                if wish["status"] == "PLAN_APPROVED"
                else "READY_TO_SCHEDULE"
            )
            if wish["status"] == "SCHEDULED":
                for ev in STORE["events"].values():
                    if ev["wish_id"] == wish["id"] and ev["status"] == "SCHEDULED":
                        ev["status"] = "CANCELLED"
                        touch(ev)
            wish["status"] = "MEDICAL_HOLD"
            touch(wish)
    return ok(ser_clearance(c))
