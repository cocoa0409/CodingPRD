"""Talkpath allocation, preemption and release."""
from flask import Blueprint

import common
import compute
import db
import enums
import response
import serialize
import validate
from errors import ApiError
from validate import DISPATCHER

bp = Blueprint("talkpaths", __name__, url_prefix=common.PREFIX)


@bp.post("/talkpath-requests")
def request_talkpath():
    actor = validate.authenticate([DISPATCHER])
    body = validate.get_body()
    site = validate.req_fk(body, "site_id", "sites")
    talkgroup = validate.req_fk(body, "talkgroup_id", "talkgroups")
    unit = validate.req_fk(body, "unit_id", "units")
    kind = validate.req_enum(body, "request_kind", enums.REQUEST_KINDS)
    event = validate.opt_fk(body, "site_event_id", "site_events")
    common.require_scope(actor, talkgroup["owner_agency_id"])
    if unit["provision_status"] == "RETIRED":
        raise ApiError("ERR_UNIT_RETIRED")
    if talkgroup["status"] != "ACTIVE":
        raise ApiError("ERR_TALKGROUP_LOCKED")
    if site["status"] == "OFF_AIR":
        raise ApiError("ERR_SITE_OFF_AIR")
    if kind == "PRIORITY" and unit["priority_class"] > compute.PRIORITY_CLASS_MAX:
        raise ApiError("ERR_EMERGENCY_PREEMPTION_NOT_PERMITTED")
    if kind == "EMERGENCY" and not unit["emergency_button_enabled"]:
        raise ApiError("ERR_EMERGENCY_PREEMPTION_NOT_PERMITTED")

    available, reserve = compute.talkpath_headroom(site)
    emergency_only = site["capacity_mode"] == "EMERGENCY_ONLY"
    victim = None
    if kind == "NORMAL":
        outcome = "BUSIED" if emergency_only or (available - reserve) <= 0 else "GRANTED"
    elif kind == "PRIORITY":
        outcome = "BUSIED" if emergency_only or available <= 0 else "GRANTED"
    else:
        if available > 0:
            outcome = "GRANTED"
        else:
            candidates = compute.preemption_candidates(site["id"])
            if not candidates:
                raise ApiError("ERR_NO_PREEMPTABLE_TALKPATH")
            victim = candidates[0]
            outcome = "GRANTED"

    row = db.base_row({
        "site_id": site["id"],
        "talkgroup_id": talkgroup["id"],
        "unit_id": unit["id"],
        "site_event_id": event["id"] if event is not None else None,
        "preempted_request_id": None,
        "request_kind": kind,
        "outcome": outcome,
        "priority_class_at_grant": None,
        "available_talkpaths_at_decision": available,
        "reserve_talkpaths_at_decision": reserve,
        "granted_at": None,
        "released_at": None,
        "hold_seconds": None,
    })
    if outcome == "GRANTED":
        row["granted_at"] = db.now()
        row["priority_class_at_grant"] = unit["priority_class"]
    if victim is not None:
        compute.preempt_request(victim)
        row["preempted_request_id"] = victim["id"]
    db.store.talkpaths[row["id"]] = row
    compute.recompute_site_counters(site)
    return response.ok(serialize.talkpath(row), 201)


@bp.get("/talkpath-requests")
def list_talkpaths():
    validate.authenticate(common.ANY_ROLE)
    filters = (
        ("site_id", validate.filter_str("site_id")),
        ("talkgroup_id", validate.filter_str("talkgroup_id")),
        ("unit_id", validate.filter_str("unit_id")),
        ("site_event_id", validate.filter_str("site_event_id")),
        ("preempted_request_id", validate.filter_str("preempted_request_id")),
        ("outcome", validate.filter_enum("outcome", enums.TALKPATH_OUTCOMES)),
        ("request_kind", validate.filter_enum("request_kind", enums.REQUEST_KINDS)),
    )
    return common.list_endpoint("talkpaths", serialize.talkpath, filters)


@bp.get("/talkpath-requests/<request_id>")
def read_talkpath(request_id):
    validate.authenticate(common.ANY_ROLE)
    row = validate.lookup("talkpaths", request_id)
    return response.ok(serialize.talkpath(row))


@bp.post("/talkpath-requests/<request_id>/release")
def release_talkpath(request_id):
    actor = validate.authenticate([DISPATCHER])
    row = validate.lookup("talkpaths", request_id)
    talkgroup = db.store.talkgroups.get(row["talkgroup_id"])
    common.require_scope(actor, talkgroup["owner_agency_id"] if talkgroup else None)
    if row["outcome"] != "GRANTED" or row["released_at"] is not None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    row["outcome"] = "RELEASED"
    row["released_at"] = db.now()
    row["hold_seconds"] = compute.hold_seconds_for(row)
    db.touch(row)
    site = db.store.sites.get(row["site_id"])
    if site is not None:
        compute.recompute_site_counters(site)
    return response.ok(serialize.talkpath(row))
