"""Roadside response: team selection, the vehicle cascade and its reversal.

A case never exists unassigned — opening one both selects a team and assigns
it, so it opens directly in TEAM_ASSIGNED.  Dispatching moves the referencing
vehicle onto the shoulder; clearing returns it to the depot and releases the
team (PRD 3.6).
"""

from flask import Blueprint, request

from db import store
from errors import fail
from middleware import (
    ANY,
    FLEET_OPERATIONS,
    REMOTE_ASSISTANCE_OPERATOR,
    SAFETY_REVIEWER,
    authenticate,
    authorize,
    body_object,
    get_or_404,
    optional_str,
    require_enum,
    require_str,
)
from response import paginate, success_array, success_object
from services import calculations as calc

bp = Blueprint("roadside", __name__)

ROAD_CLASSES = ("ARTERIAL", "FREEWAY", "RESIDENTIAL")


def _resolve(allowed):
    caller = authenticate(request.headers)
    authorize(caller, allowed)
    return caller


# ─── RoadsideTeam ─────────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/roadside-teams")
def create_roadside_team(territory_id):
    _resolve((FLEET_OPERATIONS,))
    get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    team = {
        "id": store.new_id(),
        "territory_id": territory_id,
        "team_code": require_str(body, "team_code"),
        "road_class": require_enum(body, "road_class", ROAD_CLASSES),
        "status": "AVAILABLE",
        "version": 1,
    }
    store.stamp_create(team)
    store.roadside_teams[team["id"]] = team
    return success_object(team, 201)


@bp.get("/fleet/territories/<territory_id>/roadside-teams")
def list_territory_roadside_teams(territory_id):
    _resolve((FLEET_OPERATIONS, REMOTE_ASSISTANCE_OPERATOR))
    get_or_404(store.territories, territory_id)
    rows = [row for row in store.roadside_teams.values() if row["territory_id"] == territory_id]
    rows = _filter_teams(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/roadside-teams")
def list_roadside_teams():
    _resolve((ANY,))
    rows = list(store.roadside_teams.values())
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    rows = _filter_teams(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


def _filter_teams(rows, params):
    for param, field in (("status", "status"), ("road_class", "road_class")):
        raw = params.get(param)
        if raw:
            rows = [row for row in rows if row.get(field) == raw]
    return rows


@bp.get("/fleet/roadside-teams/<team_id>")
def get_roadside_team(team_id):
    _resolve((FLEET_OPERATIONS, REMOTE_ASSISTANCE_OPERATOR))
    return success_object(get_or_404(store.roadside_teams, team_id))


@bp.get("/fleet/roadside-teams/<team_id>/roadside-cases")
def list_team_roadside_cases(team_id):
    _resolve((FLEET_OPERATIONS, REMOTE_ASSISTANCE_OPERATOR))
    get_or_404(store.roadside_teams, team_id)
    rows = [row for row in store.roadside_cases.values() if row["team_id"] == team_id]
    status = request.args.get("status")
    if status:
        rows = [row for row in rows if row["status"] == status]
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.post("/fleet/territories/<territory_id>/roadside-teams/<team_id>/mark-off-shift")
def mark_team_off_shift(territory_id, team_id):
    _resolve((FLEET_OPERATIONS,))
    get_or_404(store.territories, territory_id)
    team = get_or_404(store.roadside_teams, team_id)
    if team["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    if team["status"] == "OFF_SHIFT":
        raise fail("ERR_INVALID_STATE")
    team["status"] = "OFF_SHIFT"
    store.touch(team)
    return success_object(team)


# ─── RoadsideCase ─────────────────────────────────────────────────────────


@bp.post("/fleet/vehicles/<vehicle_id>/roadside-cases")
def open_roadside_case(vehicle_id):
    _resolve((FLEET_OPERATIONS, REMOTE_ASSISTANCE_OPERATOR))
    vehicle = get_or_404(store.vehicles, vehicle_id)
    body = body_object(request.get_json(silent=True))
    road_class = require_enum(body, "road_class", ROAD_CLASSES)
    assistance_session_id = optional_str(body, "assistance_session_id", None)
    if assistance_session_id is not None:
        get_or_404(store.assistance_sessions, assistance_session_id)

    territory_id = vehicle["territory_id"]
    territory = get_or_404(store.territories, territory_id)
    created_ops_run_index = _territory_epoch(territory_id)

    # Team selection comes before the capacity and SLA checks (PRD 3.6).
    candidates = calc.roadside_team_candidates(territory_id, road_class)
    if not candidates:
        raise fail("ERR_NO_TEAM_AVAILABLE")
    selected = candidates[0]
    if calc.dispatched_case_count(selected["id"]) >= calc.MAX_DISPATCHED_PER_TEAM:
        raise fail("ERR_TEAM_CAPACITY_EXCEEDED")

    # Response SLA: a case that has been OPEN for the whole allowance is
    # refused rather than assigned (counted in territory operations epochs).
    if _elapsed_epochs(territory_id) - created_ops_run_index >= calc.ROADSIDE_SLA_OPS_RUNS:
        raise fail("ERR_RESPONSE_SLA_BREACHED")

    case = {
        "id": store.new_id(),
        "territory_id": territory_id,
        "vehicle_id": vehicle_id,
        "assistance_session_id": assistance_session_id,
        "road_class": road_class,
        "status": "TEAM_ASSIGNED",
        "team_id": selected["id"],
        "dispatched_at": None,
        "raise_count": 0,
        "created_ops_run_index": created_ops_run_index,
        "version": 1,
    }
    store.stamp_create(case)
    store.roadside_cases[case["id"]] = case
    selected["status"] = "ON_CASE"
    store.touch(selected)
    return success_object(case, 201)


def _territory_epoch(territory_id):
    return sum(depot["ops_run_index"] for depot in store.depots.values() if depot["territory_id"] == territory_id)


def _elapsed_epochs(territory_id):
    return _territory_epoch(territory_id)


@bp.get("/fleet/territories/<territory_id>/roadside-cases")
def list_territory_roadside_cases(territory_id):
    _resolve((FLEET_OPERATIONS, REMOTE_ASSISTANCE_OPERATOR, SAFETY_REVIEWER))
    get_or_404(store.territories, territory_id)
    rows = [row for row in store.roadside_cases.values() if row["territory_id"] == territory_id]
    rows = _filter_cases(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/roadside-cases")
def list_roadside_cases():
    _resolve((ANY,))
    rows = list(store.roadside_cases.values())
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    rows = _filter_cases(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


def _filter_cases(rows, params):
    for param, field in (
        ("status", "status"),
        ("vehicle_id", "vehicle_id"),
        ("assistance_session_id", "assistance_session_id"),
        ("team_id", "team_id"),
    ):
        raw = params.get(param)
        if raw:
            rows = [row for row in rows if row.get(field) == raw]
    return rows


@bp.get("/fleet/roadside-cases/<case_id>")
def get_roadside_case(case_id):
    _resolve((FLEET_OPERATIONS, REMOTE_ASSISTANCE_OPERATOR, SAFETY_REVIEWER))
    return success_object(get_or_404(store.roadside_cases, case_id))


@bp.get("/fleet/assistance-sessions/<session_id>/roadside-cases")
def list_session_roadside_cases(session_id):
    _resolve((FLEET_OPERATIONS, REMOTE_ASSISTANCE_OPERATOR))
    get_or_404(store.assistance_sessions, session_id)
    rows = [
        row for row in store.roadside_cases.values() if row["assistance_session_id"] == session_id
    ]
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.post("/fleet/roadside-cases/<case_id>/dispatch")
def dispatch_roadside_case(case_id):
    _resolve((FLEET_OPERATIONS,))
    case = get_or_404(store.roadside_cases, case_id)
    if case["status"] != "TEAM_ASSIGNED":
        raise fail("ERR_INVALID_STATE")

    from db import format_utc

    case["status"] = "RESPONSE_DISPATCHED"
    case["dispatched_at"] = format_utc(store.now())
    case["raise_count"] = case["raise_count"] + 1
    store.touch(case)

    # Cascade: the referencing vehicle moves to ROADSIDE and is blocked.
    vehicle = store.vehicles.get(case["vehicle_id"])
    if vehicle is not None:
        vehicle["status"] = "ROADSIDE"
        vehicle["is_roadside_blocked"] = True
        store.touch(vehicle)
        calc.recompute_service_status(vehicle, bump=False)
    return success_object(case)


@bp.post("/fleet/roadside-cases/<case_id>/clear")
def clear_roadside_case(case_id):
    _resolve((FLEET_OPERATIONS,))
    case = get_or_404(store.roadside_cases, case_id)
    if case["status"] != "RESPONSE_DISPATCHED":
        raise fail("ERR_INVALID_STATE")

    case["status"] = "CLEARED"
    store.touch(case)

    vehicle = store.vehicles.get(case["vehicle_id"])
    if vehicle is not None:
        vehicle["status"] = "AT_DEPOT"
        vehicle["is_roadside_blocked"] = False
        store.touch(vehicle)
        calc.recompute_service_status(vehicle, bump=False)
    calc.release_team_if_idle(case["team_id"])
    return success_object(case)


@bp.post("/fleet/roadside-cases/<case_id>/cancel")
def cancel_roadside_case(case_id):
    _resolve((FLEET_OPERATIONS,))
    case = get_or_404(store.roadside_cases, case_id)
    if case["status"] not in ("OPEN", "TEAM_ASSIGNED"):
        raise fail("ERR_INVALID_STATE")
    case["status"] = "CANCELLED"
    store.touch(case)
    calc.release_team_if_idle(case["team_id"])
    return success_object(case)