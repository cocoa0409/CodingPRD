"""EmergencyAction endpoints: recommend, order, lift (PRD §3.9)."""
from flask import Blueprint, request

from auth import authenticate, require_role
from calculations import evacuation_buffer_conflict
from constants import ACTION_TYPES
from db import STORE, now
from errors import api_error
from serialize import serialize
from util import base_entity, envelope, get_body, list_response, parse_dt, touch

bp = Blueprint("emergency", __name__, url_prefix="/alerts")

MANAGER = ["EmergencyManager"]
ANY_ROLE = ["PlatformAdmin", "Forecaster", "MeteorologistInCharge", "VerificationAnalyst", "EmergencyManager"]


def _get_action_or_404(action_id):
    action = STORE["emactions"].get(action_id)
    if action is None:
        raise api_error(
            "ERR_EMERGENCY_ACTION_NOT_FOUND", "EmergencyAction %s does not exist." % action_id
        )
    return action


@bp.post("/emergency-actions")
def create_action():
    role, uid, _fc = authenticate()
    require_role(role, MANAGER)
    body = get_body()
    # tier 4: schema
    zone_id = body.get("zone_id")
    product_id = body.get("product_id")
    if not isinstance(zone_id, str) or not zone_id:
        raise api_error("ERR_INVALID_REQUEST", "zone_id is required.")
    if not isinstance(product_id, str) or not product_id:
        raise api_error("ERR_INVALID_REQUEST", "product_id is required.")
    action_type = body.get("action_type")
    if action_type not in ACTION_TYPES:
        raise api_error("ERR_INVALID_REQUEST", "action_type must be one of %s" % ACTION_TYPES)
    effective_from = parse_dt(body.get("effective_from"))
    effective_until = parse_dt(body.get("effective_until"))
    if effective_from is None or effective_until is None:
        raise api_error(
            "ERR_INVALID_REQUEST", "effective_from and effective_until are required and must be ISO 8601."
        )
    # tier 5: body FK existence (zone, then product)
    if STORE["zones"].get(zone_id) is None:
        raise api_error("ERR_ZONE_NOT_FOUND", "CountyZone %s does not exist." % zone_id)
    if STORE["products"].get(product_id) is None:
        raise api_error("ERR_PRODUCT_NOT_FOUND", "Product %s does not exist." % product_id)
    # tier 9: planned window
    if not effective_until > effective_from:
        raise api_error(
            "ERR_WINDOW_INVALID", "effective_until must lie strictly after effective_from."
        )
    action = base_entity()
    action.update({
        "zone_id": zone_id,
        "product_id": product_id,
        "action_type": action_type,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "status": "RECOMMENDED",
        "decided_by": uid,
        "ordered_at": None,
        "lifted_at": None,
    })
    STORE["emactions"][action["id"]] = action
    return envelope(serialize(action), "object", 201)


@bp.get("/emergency-actions/<action_id>")
def get_action(action_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    return envelope(serialize(_get_action_or_404(action_id)), "object", 200)


@bp.get("/emergency-actions")
def list_actions():
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    rows = list(STORE["emactions"].values())
    for field in ("zone_id", "product_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [a for a in rows if a.get(field) == value]
    return list_response(rows, serialize)


@bp.post("/emergency-actions/<action_id>/order")
def order_action(action_id):
    role, _uid, _fc = authenticate()
    require_role(role, MANAGER)
    action = _get_action_or_404(action_id)
    # tier 7: state machine preconditions
    if action["status"] != "RECOMMENDED":
        raise api_error(
            "ERR_INVALID_EM_ACTION_STATE", "Only a RECOMMENDED action can be ordered."
        )
    product = STORE["products"].get(action["product_id"])
    if product is None or product["status"] != "ISSUED":
        raise api_error(
            "ERR_INVALID_PRODUCT_STATE", "The linked product must currently be ISSUED."
        )
    # tier 10: evacuation re-entry buffer
    if evacuation_buffer_conflict(action):
        raise api_error(
            "ERR_EVACUATION_WINDOW_CONFLICT",
            "EVACUATION order violates the 60-minute re-entry buffer.",
        )
    # tier 11: zone coverage by the linked product
    if action["zone_id"] not in product["resolved_zone_ids"]:
        raise api_error(
            "ERR_ZONE_NOT_COVERED_BY_PRODUCT",
            "The action's zone is not in the linked product's resolved_zone_ids.",
        )
    action["status"] = "ORDERED"
    action["ordered_at"] = now()
    touch(action)
    return envelope(serialize(action), "object", 200)


@bp.post("/emergency-actions/<action_id>/lift")
def lift_action(action_id):
    role, _uid, _fc = authenticate()
    require_role(role, MANAGER)
    action = _get_action_or_404(action_id)
    if action["status"] == "ORDERED":
        action["status"] = "LIFTED"
        action["lifted_at"] = now()
        touch(action)
    elif action["status"] == "RECOMMENDED":
        # the same endpoint withdraws a still-RECOMMENDED recommendation
        action["status"] = "WITHDRAWN"
        touch(action)
    else:
        raise api_error(
            "ERR_INVALID_EM_ACTION_STATE", "Only an ORDERED or RECOMMENDED action can be lifted."
        )
    return envelope(serialize(action), "object", 200)
