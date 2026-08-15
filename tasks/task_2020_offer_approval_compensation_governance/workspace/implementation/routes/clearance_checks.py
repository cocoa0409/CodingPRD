"""ClearanceCheck endpoints."""

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_OFFER_NOT_FOUND, ERR_CLEARANCE_CHECK_NOT_FOUND,
    ERR_INVALID_OFFER_STATE, ERR_DUPLICATE_ACTIVE_CHECK,
    ERR_CHECK_INVALID_TRANSITION, ERR_INVALID_REQUEST,
)
from middleware import (
    get_actor, require_role, get_json_body, validate_fields, req_enum, req_string,
)
from response import success
from services import calc
from services import offer_ops

bp = Blueprint("clearance_checks", __name__)

READ_ROLES = ["Recruiter", "HiringManager", "HRAdmin", "VPPeople", "BackgroundScreener"]

# Declared edges of the ClearanceCheck machine (transition endpoint only)
EDGES = {
    "INITIATED": {"IN_PROGRESS"},
    "IN_PROGRESS": {"CLEARED", "FLAGGED"},
    "FLAGGED": {"IN_PROGRESS", "FAILED"},
}


@bp.route("/api/offers/<offer_id>/clearance-checks", methods=["POST"])
def create(offer_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["kind"], [])
    kind = req_enum(body, "kind", ["BACKGROUND", "REFERENCE"])
    require_role(role, ["BackgroundScreener"])
    offer = db.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Offer not found")
    if offer["status"] != "ACCEPTED":
        raise_err(ERR_INVALID_OFFER_STATE, "Checks may only be initiated on an ACCEPTED offer")
    for c in db.clearance_checks.values():
        if (c["offer_id"] == offer_id and c["kind"] == kind
                and c["status"] in ("INITIATED", "IN_PROGRESS", "FLAGGED")):
            raise_err(ERR_DUPLICATE_ACTIVE_CHECK,
                      "A check of this kind is already active")
    ts = db.now_ms()
    check = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "offer_id": offer_id,
        "kind": kind,
        "status": "INITIATED",
        "note": None,
    }
    db.clearance_checks[check["id"]] = check
    offer_ops.append_event(offer_id, "CHECK_INITIATED", uid, f"kind={kind}")
    offer_ops.recompute_posture_and_resolve(offer, uid)
    return success(check, status=201)


@bp.route("/api/offers/<offer_id>/clearance-checks", methods=["GET"])
def list_checks(offer_id):
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    offer = db.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Offer not found")
    items = sorted(
        [c for c in db.clearance_checks.values() if c["offer_id"] == offer_id],
        key=lambda c: c["created_at"],
    )
    return success(items, response_type="array")


@bp.route("/api/clearance-checks/<check_id>/transition", methods=["POST"])
def transition(check_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["to"], ["note"])
    to = req_enum(body, "to",
                  ["INITIATED", "IN_PROGRESS", "CLEARED", "FLAGGED", "FAILED",
                   "WAIVED", "CANCELLED"])
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise_err(ERR_INVALID_REQUEST, "note must be a string")
    require_role(role, ["BackgroundScreener"])
    check = db.clearance_checks.get(check_id)
    if check is None:
        raise_err(ERR_CLEARANCE_CHECK_NOT_FOUND, "Clearance check not found")
    if to not in EDGES.get(check["status"], set()):
        raise_err(ERR_CHECK_INVALID_TRANSITION,
                  f"{check['status']} -> {to} is not a declared edge")
    check["status"] = to
    if note is not None:
        check["note"] = note
    calc.touch(check)
    offer = db.offers[check["offer_id"]]
    offer_ops.append_event(offer["id"], "CHECK_TRANSITIONED", uid,
                           f"kind={check['kind']};to={to}")
    offer_ops.recompute_posture_and_resolve(offer, uid)
    return success(check)


@bp.route("/api/clearance-checks/<check_id>/waive", methods=["POST"])
def waive(check_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["reason"], [])
    reason = req_string(body, "reason")
    require_role(role, ["VPPeople"])
    check = db.clearance_checks.get(check_id)
    if check is None:
        raise_err(ERR_CLEARANCE_CHECK_NOT_FOUND, "Clearance check not found")
    if check["status"] not in ("IN_PROGRESS", "FLAGGED"):
        raise_err(ERR_CHECK_INVALID_TRANSITION,
                  "Only IN_PROGRESS or FLAGGED checks may be waived")
    check["status"] = "WAIVED"
    check["note"] = reason
    calc.touch(check)
    offer = db.offers[check["offer_id"]]
    offer_ops.append_event(offer["id"], "CHECK_WAIVED", uid, f"kind={check['kind']}")
    offer_ops.recompute_posture_and_resolve(offer, uid)
    return success(check)
