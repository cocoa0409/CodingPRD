"""Software campaign endpoints (PRD section 3.7)."""

from flask import Blueprint

import calc
import errors as E
import store
from errors import ApiError
from routes_vehicles import recompute_hold_count
from store import DB
from util import (auth, require_role, body, req_field, as_str, as_enum, find,
                  ok)

bp = Blueprint("software", __name__)

_CAMPAIGN_READ_ROLES = {"PlatformAdmin", "ReleaseManager", "TelematicsIngestion"}


@bp.post("/evfleet/software-campaigns")
def create_campaign():
    _, role = auth()
    require_role(role, {"ReleaseManager"})
    b = body()
    target_version = as_str(req_field(b, "target_version"), "target_version")
    scope = as_enum(req_field(b, "telematics_tier_scope"),
                    {"STANDARD", "ADVANCED", "ALL"}, "telematics_tier_scope")
    e = {
        "target_version": target_version,
        "telematics_tier_scope": scope,
        "status": "DRAFT",
        "paused_from": None,
        "results": [],
        "succeeded_count": 0,
        "failed_count": 0,
    }
    store.stamp_new(e)
    DB.campaigns[e["id"]] = e
    return ok(store.public(e), 201)


@bp.get("/evfleet/software-campaigns/<cid>")
def get_campaign(cid):
    _, role = auth()
    require_role(role, _CAMPAIGN_READ_ROLES)
    e = find(DB.campaigns, cid, "software campaign")
    return ok(store.public(e), 200)


_CAMPAIGN_STATES = {"CANARY", "EXPANDED", "GENERAL", "PAUSED", "COMPLETE",
                    "ROLLED_BACK"}


@bp.post("/evfleet/software-campaigns/<cid>/transition")
def transition_campaign(cid):
    _, role = auth()
    require_role(role, {"ReleaseManager"})
    c = find(DB.campaigns, cid, "software campaign")
    b = body()
    to_state = as_str(req_field(b, "to_state"), "to_state")
    if to_state not in _CAMPAIGN_STATES:
        raise ApiError(E.ERR_VALIDATION, 400, "unknown to_state %r" % to_state)
    # priority 6: terminal lockdown, then state preconditions
    if c["status"] in ("COMPLETE", "ROLLED_BACK"):
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                       "software campaign is in terminal state %s" % c["status"])
    st = c["status"]
    gate_min = None
    if to_state == "CANARY":
        if st == "DRAFT":
            pass
        elif st == "PAUSED" and c["paused_from"] == "CANARY":
            pass
        else:
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "CANARY is offered from DRAFT, or from PAUSED when "
                           "paused_from is CANARY")
    elif to_state == "EXPANDED":
        if st == "CANARY":
            gate_min = calc.CANARY_MIN_COHORT
        elif st == "PAUSED" and c["paused_from"] == "EXPANDED":
            pass
        else:
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "EXPANDED is offered from CANARY, or from PAUSED when "
                           "paused_from is EXPANDED")
    elif to_state == "GENERAL":
        if st == "EXPANDED":
            gate_min = calc.EXPANDED_MIN_COHORT
        elif st == "PAUSED" and c["paused_from"] == "GENERAL":
            pass
        else:
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "GENERAL is offered from EXPANDED, or from PAUSED when "
                           "paused_from is GENERAL")
    elif to_state == "COMPLETE":
        if st != "GENERAL":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "COMPLETE is offered from GENERAL")
    elif to_state == "PAUSED":
        if st not in ("CANARY", "EXPANDED", "GENERAL"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "PAUSED is offered from CANARY, EXPANDED, or GENERAL")
    elif to_state == "ROLLED_BACK":
        if st not in ("CANARY", "EXPANDED", "GENERAL", "PAUSED"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "ROLLED_BACK is offered from CANARY, EXPANDED, GENERAL, "
                           "or PAUSED")
    # priority 15: rollout gate on forward stage advance
    if gate_min is not None:
        calc.check_rollout_gate(c, gate_min)
    # apply
    if to_state == "PAUSED":
        c["paused_from"] = st
    elif st == "PAUSED":
        # resume returns to exactly the recorded stage and clears paused_from
        c["paused_from"] = None
    c["status"] = to_state
    if to_state == "ROLLED_BACK":
        # cascade link 1: held vehicles (SUCCESS result + telematics ACTIVE)
        affected_orders = set()
        for entry in c["results"]:
            if entry["result"] != "SUCCESS":
                continue
            v = DB.vehicles.get(entry["vehicle_id"])
            if v is None or v["telematics_status"] != "ACTIVE":
                continue
            v["software_hold"] = True
            # cascade link 2: held vans en route are recalled
            if v["delivery_status"] == "IN_TRANSIT":
                v["delivery_status"] = "ASSEMBLED"
            store.touch(v)
            affected_orders.add(v["vehicle_order_id"])
        # cascade link 3: affected orders' hold_count recomputed
        for oid in affected_orders:
            recompute_hold_count(DB.orders[oid])
    store.touch(c)
    return ok(store.public(c), 200)


@bp.post("/evfleet/software-campaigns/<cid>/vehicle-results")
def record_vehicle_result(cid):
    _, role = auth()
    require_role(role, {"TelematicsIngestion"})
    c = find(DB.campaigns, cid, "software campaign")
    b = body()
    vehicle_id = as_str(req_field(b, "vehicle_id"), "vehicle_id")
    v = find(DB.vehicles, vehicle_id, "vehicle")
    # priority 6: campaign must be actively rolling out
    if c["status"] not in ("CANARY", "EXPANDED", "GENERAL"):
        raise ApiError(E.ERR_CAMPAIGN_NOT_ACTIVE, 409,
                       "campaign is not in CANARY, EXPANDED, or GENERAL")
    result = as_enum(req_field(b, "result"), {"SUCCESS", "FAILED"}, "result")
    # priority 13: telematics ACTIVE and tier in scope
    if v["telematics_status"] != "ACTIVE":
        raise ApiError(E.ERR_TELEMATICS_NOT_ACTIVE, 409,
                       "campaign results require telematics ACTIVE")
    order = DB.orders[v["vehicle_order_id"]]
    scope = c["telematics_tier_scope"]
    if scope != "ALL" and order["telematics_tier"] != scope:
        raise ApiError(E.ERR_VALIDATION, 400,
                       "vehicle telematics tier is outside the campaign scope")
    # priority 15: one result per vehicle
    if any(e["vehicle_id"] == vehicle_id for e in c["results"]):
        raise ApiError(E.ERR_DUPLICATE_VEHICLE_RESULT, 409,
                       "a result for this vehicle already exists in the campaign")
    c["results"].append({
        "vehicle_id": vehicle_id,
        "result": result,
        "reported_at": store.now_str(),
    })
    c["succeeded_count"] = sum(1 for e in c["results"] if e["result"] == "SUCCESS")
    c["failed_count"] = sum(1 for e in c["results"] if e["result"] == "FAILED")
    if result == "SUCCESS":
        v["software_version"] = c["target_version"]
        store.touch(v)
    store.touch(c)
    return ok(store.public(c), 201)
