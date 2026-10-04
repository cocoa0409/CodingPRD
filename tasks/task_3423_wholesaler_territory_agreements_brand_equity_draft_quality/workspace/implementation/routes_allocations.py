"""Limited-release allocation events: requests, waterfall lock, assignment
decisions (§3.5)."""

from flask import Blueprint

import calc
import clock
import db
from auth import (ALL_ROLES, ROLE_BREWER_ADMIN, ROLE_WHOLESALER_PRINCIPAL,
                  require_roles)
from db import touch
from envelope import created, ok
from errors import (ApiError, ERR_BRAND_SCOPE_MISMATCH, ERR_DUPLICATE_REQUEST,
                    ERR_INVALID_STATE_TRANSITION, ERR_NOT_FOUND,
                    ERR_NOT_RESOURCE_OWNER, ERR_WHOLESALER_NOT_ELIGIBLE)
from validate import field, get_body, validate_body

bp = Blueprint("allocations", __name__)


@bp.route("/allocation-events", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def create_event(user_id, caller_role):
    data, _ = validate_body(get_body(), {
        "brand_code": field("string", required=True),
        "total_qty_cases": field("integer", required=True),
        "min_guarantee_cases": field("integer", default=100),
        "territory_cap_pct": field("number", default=0.40),
    })
    event = db.stamped()
    event.update({
        "brand_code": data["brand_code"],
        "total_qty_cases": data["total_qty_cases"],
        "min_guarantee_cases": data["min_guarantee_cases"],
        "territory_cap_pct": data["territory_cap_pct"],
        "status": "OPEN",
        "requests": [],
        "assignments": [],
        "unassigned_remainder": None,
        "committed_qty": 0,
        "pending_qty": 0,
        "released_qty": 0,
    })
    db.allocation_events[event["id"]] = event
    return created(event)


@bp.route("/allocation-events/<eid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_event(eid, user_id, caller_role):
    event = db.allocation_events.get(eid)
    if event is None:
        raise ApiError(ERR_NOT_FOUND, "Allocation event not found", 404)
    return ok(event)


@bp.route("/allocation-events/<eid>/requests", methods=["POST"])
@require_roles(ROLE_WHOLESALER_PRINCIPAL)
def create_request(eid, user_id, caller_role):
    event = db.allocation_events.get(eid)
    if event is None:
        raise ApiError(ERR_NOT_FOUND, "Allocation event not found", 404)
    data, _ = validate_body(get_body(), {
        "requested_qty_cases": field("integer", required=True),
    })
    wholesaler = db.wholesalers.get(user_id)
    if wholesaler is None:
        raise ApiError(ERR_NOT_FOUND, "Wholesaler not found", 404)
    if event["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Requests require an OPEN event", 409)
    if wholesaler["status"] != "APPOINTED":
        raise ApiError(ERR_WHOLESALER_NOT_ELIGIBLE,
                       "Only an APPOINTED wholesaler may request an allocation",
                       409)
    if not db.brand_in_scope(wholesaler["id"], event["brand_code"]):
        raise ApiError(ERR_BRAND_SCOPE_MISMATCH,
                       "The event brand is outside the wholesaler's ACTIVE "
                       "agreement brand scope", 422)
    for entry in event["requests"]:
        if entry["wholesaler_id"] == wholesaler["id"]:
            raise ApiError(ERR_DUPLICATE_REQUEST,
                           "The wholesaler already has a request on this event",
                           409)
    event["requests"].append({
        "wholesaler_id": wholesaler["id"],
        "requested_qty_cases": data["requested_qty_cases"],
        "created_at": clock.now_iso(),
    })
    touch(event)
    return created(event)


@bp.route("/allocation-events/<eid>/lock", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def lock_event(eid, user_id, caller_role):
    event = db.allocation_events.get(eid)
    if event is None:
        raise ApiError(ERR_NOT_FOUND, "Allocation event not found", 404)
    if event["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Locking requires an OPEN event", 409)
    if not event["requests"]:
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Locking requires at least one eligible request", 409)
    waterfall_input = []
    for entry in event["requests"]:
        wholesaler = db.wholesalers.get(entry["wholesaler_id"])
        tier = wholesaler["tier"] if wholesaler is not None else "BRONZE"
        waterfall_input.append({
            "requested_qty_cases": entry["requested_qty_cases"],
            "created_at": entry["created_at"],
            "_tier": tier,
        })
    assigned = calc.waterfall_assignments(waterfall_input,
                                          event["total_qty_cases"],
                                          event["min_guarantee_cases"],
                                          event["territory_cap_pct"])
    assignments = []
    for i, entry in enumerate(event["requests"]):
        assignments.append({
            "wholesaler_id": entry["wholesaler_id"],
            "tier_snapshot": waterfall_input[i]["_tier"],
            "requested_qty_cases": entry["requested_qty_cases"],
            "assigned_qty": assigned[i],
            "status": "PENDING",
        })
    total_assigned = sum(assigned)
    event["assignments"] = assignments
    event["unassigned_remainder"] = event["total_qty_cases"] - total_assigned
    event["pending_qty"] = total_assigned
    event["committed_qty"] = 0
    event["released_qty"] = 0
    event["status"] = "LOCKED"
    touch(event)
    return ok(event)


@bp.route("/allocation-events/<eid>/assignments/<wholesaler_id>/decision",
          methods=["POST"])
@require_roles(ROLE_WHOLESALER_PRINCIPAL)
def assignment_decision(eid, wholesaler_id, user_id, caller_role):
    if wholesaler_id != user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER,
                       "A wholesaler may only decide its own assignment", 403)
    event = db.allocation_events.get(eid)
    if event is None:
        raise ApiError(ERR_NOT_FOUND, "Allocation event not found", 404)
    data, _ = validate_body(get_body(), {
        "decision": field("enum", required=True, enum=("CONFIRM", "RELEASE")),
    })
    assignment = None
    for candidate in event["assignments"]:
        if candidate["wholesaler_id"] == wholesaler_id:
            assignment = candidate
            break
    if assignment is None:
        raise ApiError(ERR_NOT_FOUND,
                       "No assignment for this wholesaler on this event", 404)
    if event["status"] not in ("LOCKED", "CLOSED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Assignment decisions require a LOCKED or CLOSED event",
                       409)
    qty = assignment["assigned_qty"]
    if data["decision"] == "CONFIRM":
        if assignment["status"] != "PENDING":
            raise ApiError(ERR_INVALID_STATE_TRANSITION,
                           "CONFIRM requires a PENDING assignment", 409)
        assignment["status"] = "CONFIRMED"
        event["pending_qty"] -= qty
        event["committed_qty"] += qty
    else:
        if assignment["status"] not in ("PENDING", "CONFIRMED"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION,
                           "RELEASE requires a PENDING or CONFIRMED assignment",
                           409)
        if assignment["status"] == "PENDING":
            event["pending_qty"] -= qty
        else:
            event["committed_qty"] -= qty
        assignment["status"] = "RELEASED"
        event["released_qty"] += qty
    if event["status"] == "LOCKED" and event["pending_qty"] == 0:
        event["status"] = "CLOSED"
    touch(event)
    return ok(event)
