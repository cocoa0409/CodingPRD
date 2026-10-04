"""Stringer roster, assignments, check-in, and coordinator status actions
(PRD §3.3)."""
from flask import Blueprint, request

from auth import require_roles, body
from clock import now as clock_now
from envelope import ok_object, paginate
from errors import raise_err
from loaders import (
    get_event, get_county, get_stringer, get_assignment, require_posture,
    versioned_record, touch,
)
from serializers import stringer_json, assignment_json
from services_rules import has_overlap, auto_select_stringer
from store import db
from util import parse_datetime, nonblank

bp = Blueprint("stringers", __name__)

COORD_ROLES = ("StringerCoordinator", "ElectionOpsAdmin")
ASSIGNMENT_STATUSES = ("SCHEDULED", "ACTIVE", "RELEASED", "NO_SHOW")


@bp.post("/stringers")
def create_stringer():
    require_roles("StringerCoordinator")
    data = body()
    for f in ("stringer_name", "home_state"):
        if f not in data or data[f] is None:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    if not nonblank(data["stringer_name"]):
        raise_err("ERR_INVALID_REQUEST", "stringer_name must be a non-blank string")
    if not nonblank(data["home_state"]):
        raise_err("ERR_INVALID_REQUEST", "home_state must be a non-blank string")
    rec = versioned_record()
    rec.update({
        "stringer_name": data["stringer_name"],
        "home_state": data["home_state"],
        "no_show_count": 0,
        "accepted_report_count": 0,
        "voided_report_count": 0,
        # Incident log driving stringer_reliability_score; both variants are
        # derived from it on read / at selection time.
        "reliability_events": [],
    })
    db["stringers"][rec["id"]] = rec
    return ok_object(stringer_json(rec), 201)


@bp.get("/stringers/<rid>")
def read_stringer(rid):
    require_roles(*COORD_ROLES)
    return ok_object(stringer_json(get_stringer(rid)))


@bp.post("/election-events/<rid>/assignments")
def create_assignment(rid):
    require_roles("StringerCoordinator")
    event = get_event(rid)
    require_posture(event, "SETUP", "CANDIDATES_LOCKED")
    data = body()
    for f in ("county_id", "window_start", "window_end"):
        if f not in data or data[f] is None:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    county = db["counties"].get(data["county_id"])
    if county is None:
        raise_err("ERR_COUNTY_NOT_FOUND", "County id does not resolve")
    # Priority 10: cross-event reference.
    if county["event_id"] != event["id"]:
        raise_err("ERR_CROSS_EVENT_REFERENCE", "County belongs to another event")
    ws = parse_datetime(data["window_start"])
    we = parse_datetime(data["window_end"])
    if ws is None or we is None:
        raise_err("ERR_INVALID_REQUEST", "window_start/window_end must be ISO 8601 UTC instants")
    # Priority 13: interval well-formedness precedes overlap and selector.
    if not (ws < we):
        raise_err("ERR_INVALID_REQUEST", "window_start must be strictly before window_end")

    stringer_id = data.get("stringer_id")
    auto = False
    if stringer_id is not None:
        stringer = get_stringer(stringer_id)
        # Priority 14: overlap guard for an explicitly named stringer.
        if has_overlap(stringer["id"], ws, we):
            raise_err(
                "ERR_ASSIGNMENT_WINDOW_OVERLAP",
                "Requested window overlaps a SCHEDULED/ACTIVE assignment",
            )
    else:
        # Priority 18: auto-selector per the event's ranking mode.
        stringer = auto_select_stringer(event, ws, we)
        if stringer is None:
            raise_err("ERR_NO_ELIGIBLE_STRINGER", "No eligible stringer for the window")
        auto = True

    rec = versioned_record()
    rec.update({
        "event_id": event["id"],
        "county_id": county["id"],
        "stringer_id": stringer["id"],
        "window_start": ws,
        "window_end": we,
        "status": "SCHEDULED",
        "auto_selected": auto,
    })
    db["assignments"][rec["id"]] = rec
    return ok_object(assignment_json(rec), 201)


@bp.get("/election-events/<rid>/assignments")
def list_assignments_of_event(rid):
    require_roles(*COORD_ROLES)
    event = get_event(rid)
    rows = [a for a in db["assignments"].values() if a["event_id"] == event["id"]]
    status = request.args.get("status")
    if status is not None:
        if status not in ASSIGNMENT_STATUSES:
            raise_err("ERR_INVALID_REQUEST", "status filter out of range")
        rows = [a for a in rows if a["status"] == status]
    return paginate(rows, assignment_json)


@bp.get("/stringers/<rid>/assignments")
def list_assignments_of_stringer(rid):
    require_roles(*COORD_ROLES)
    stringer = get_stringer(rid)
    rows = [a for a in db["assignments"].values() if a["stringer_id"] == stringer["id"]]
    return paginate(rows, assignment_json)


@bp.get("/counties/<rid>/assignments")
def list_assignments_of_county(rid):
    require_roles(*COORD_ROLES)
    county = get_county(rid)
    rows = [a for a in db["assignments"].values() if a["county_id"] == county["id"]]
    return paginate(rows, assignment_json)


@bp.post("/assignments/<rid>/check-in")
def check_in(rid):
    uid, _ = require_roles("Stringer")
    a = get_assignment(rid)
    # Priority 3: entity-backed ownership — self-service check-in only.
    if uid != a["stringer_id"]:
        raise_err("ERR_UNAUTHORIZED_ROLE", "X-User-ID must equal the assignment's stringer")
    event = get_event(a["event_id"])
    require_posture(event, "LIVE", "TABULATION")
    if a["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Check-in requires status SCHEDULED")
    now = clock_now()
    if not (a["window_start"] <= now < a["window_end"]):
        raise_err("ERR_OUTSIDE_ASSIGNMENT_WINDOW", "Clock outside the assignment window")
    a["status"] = "ACTIVE"
    touch(a)
    return ok_object(assignment_json(a))


@bp.post("/assignments/<rid>/status-actions")
def status_action(rid):
    require_roles("StringerCoordinator")
    a = get_assignment(rid)
    data = body()
    action = data.get("action")
    if action not in ("RELEASE", "NO_SHOW", "REDEPLOY"):
        raise_err("ERR_INVALID_REQUEST", "action must be RELEASE, NO_SHOW or REDEPLOY")
    now = clock_now()
    if action == "RELEASE":
        if a["status"] != "ACTIVE":
            raise_err("ERR_INVALID_STATE", "RELEASE requires status ACTIVE")
        a["status"] = "RELEASED"
    elif action == "NO_SHOW":
        if a["status"] != "SCHEDULED":
            raise_err("ERR_INVALID_STATE", "NO_SHOW requires status SCHEDULED")
        if not (now >= a["window_end"]):
            raise_err(
                "ERR_OUTSIDE_ASSIGNMENT_WINDOW",
                "NO_SHOW admitted only at or after window_end",
            )
        a["status"] = "NO_SHOW"
        # Side effect: no_show_count += 1 and reliability recompute.
        stringer = db["stringers"][a["stringer_id"]]
        stringer["no_show_count"] += 1
        stringer["reliability_events"].append(
            {"event_id": a["event_id"], "kind": "no_show"}
        )
        touch(stringer)
    else:  # REDEPLOY
        if a["status"] != "RELEASED":
            raise_err("ERR_INVALID_STATE", "REDEPLOY requires status RELEASED")
        if not (now < a["window_end"]):
            raise_err(
                "ERR_OUTSIDE_ASSIGNMENT_WINDOW",
                "REDEPLOY requires the clock strictly before window_end",
            )
        a["status"] = "ACTIVE"
    touch(a)
    return ok_object(assignment_json(a))
