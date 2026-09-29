"""Proctoring stations and proctored exam sessions (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint

import derive
import validate as v
from auth import endpoint, scope_center
from envelope import created, ok, ok_list
from errors import ApiError
from helpers import eq, get_center, get_enrollment, get_proctor_session, get_station, q
from store import new_row, ordered, store, touch

bp = Blueprint("proctoring", __name__)

STATION_TYPES = ("COMPUTER", "PAPER")
TURNAROUND_BUFFER_MINUTES = 15


def _placement_center_of(enrollment):
    return store.placements[enrollment["placement_id"]]["center_id"]


# ---------------------------------------------------------------- stations
@bp.post("/proctor-stations")
@endpoint("DistrictAdmin", "PlacementCoordinator")
def create_station(ctx):
    b = v.body()
    center_id = v.req_str(b, "center_id", 1, None)
    label = v.req_str(b, "label", 1, 32)
    station_type = v.req_enum(b, "station_type", STATION_TYPES)
    get_center(center_id)
    scope_center(ctx, center_id)
    row = new_row(center_id=center_id, label=label, station_type=station_type,
                  turnaround_buffer_minutes=TURNAROUND_BUFFER_MINUTES)
    store.stations[row["id"]] = row
    return created(derive.ser_station(row))


@bp.get("/proctor-stations/<proctor_station_id>")
@endpoint("DistrictAdmin", "PlacementCoordinator", "Registrar")
def read_station(ctx, proctor_station_id):
    row = get_station(proctor_station_id)
    scope_center(ctx, row["center_id"])
    return ok(derive.ser_station(row))


@bp.get("/proctor-stations")
@endpoint("DistrictAdmin", "PlacementCoordinator", "Registrar")
def list_stations(ctx):
    rows = ordered(store.stations.values())
    if ctx.role == "PlacementCoordinator":
        rows = [r for r in rows if r["center_id"] == ctx.uid]
    rows = eq(rows, "center_id", q("center_id"))
    rows = eq(rows, "station_type", q("station_type"))
    return ok_list(rows, derive.ser_station)


# ---------------------------------------------------------------- sessions
@bp.post("/proctor-sessions")
@endpoint("PlacementCoordinator")
def create_proctor_session(ctx):
    b = v.body()
    enrollment_id = v.req_str(b, "course_enrollment_id", 1, None)
    station_id = v.req_str(b, "proctor_station_id", 1, None)
    start = v.req_dt(b, "scheduled_start")
    end = v.req_dt(b, "scheduled_end")
    enrollment = get_enrollment(enrollment_id)
    station = get_station(station_id)
    scope_center(ctx, _placement_center_of(enrollment))
    if end <= start:
        raise ApiError("ERR_INVALID_INTERVAL",
                       "scheduled_end must be later than scheduled_start")
    course = store.courses[enrollment["course_id"]]
    if not course["proctoring_required"]:
        raise ApiError("ERR_PROCTORING_POLICY_VIOLATION",
                       "the course does not require a proctored exam")
    if station["center_id"] != _placement_center_of(enrollment):
        raise ApiError("ERR_STATION_CENTER_MISMATCH",
                       "the station sits in another center")
    buffer_delta = timedelta(minutes=station["turnaround_buffer_minutes"])
    for other in store.proctor_sessions.values():
        if other["proctor_station_id"] != station_id:
            continue
        if other["status"] not in derive.OCCUPYING_SESSION_STATES:
            continue
        if other.get("_released"):
            continue
        if start < other["scheduled_end"] + buffer_delta and end > other["scheduled_start"]:
            raise ApiError("ERR_STATION_CONFLICT",
                           "the station is occupied for that interval")
    row = new_row(course_enrollment_id=enrollment_id, proctor_station_id=station_id,
                  scheduled_start=start, scheduled_end=end, status="SCHEDULED",
                  score_percent=None, integrity_incident=None, no_show_note=None)
    store.proctor_sessions[row["id"]] = row
    return created(derive.ser_proctor_session(row))


@bp.get("/proctor-sessions/<proctor_session_id>")
@endpoint("PlacementCoordinator", "DistrictAdmin", "Registrar")
def read_proctor_session(ctx, proctor_session_id):
    row = get_proctor_session(proctor_session_id)
    scope_center(ctx, store.stations[row["proctor_station_id"]]["center_id"])
    return ok(derive.ser_proctor_session(row))


@bp.get("/proctor-sessions")
@endpoint("PlacementCoordinator", "DistrictAdmin", "Registrar")
def list_proctor_sessions(ctx):
    rows = ordered(store.proctor_sessions.values())
    if ctx.role == "PlacementCoordinator":
        rows = [r for r in rows
                if store.stations[r["proctor_station_id"]]["center_id"] == ctx.uid]
    rows = eq(rows, "course_enrollment_id", q("course_enrollment_id"))
    rows = eq(rows, "proctor_station_id", q("proctor_station_id"))
    rows = eq(rows, "status", q("status"))
    return ok_list(rows, derive.ser_proctor_session)


@bp.post("/proctor-sessions/<proctor_session_id>/complete")
@endpoint("PlacementCoordinator")
def complete_proctor_session(ctx, proctor_session_id):
    session = get_proctor_session(proctor_session_id)
    scope_center(ctx, store.stations[session["proctor_station_id"]]["center_id"])
    b = v.body()
    score = v.req_num(b, "score_percent", lo=0, hi=100, dp=2)
    incident = v.opt_bool(b, "integrity_incident", default=False)
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "only a SCHEDULED session may be completed")
    session["status"] = "COMPLETED"
    session["score_percent"] = score
    session["integrity_incident"] = incident
    touch(session)
    if incident:
        enrollment = store.enrollments.get(session["course_enrollment_id"])
        if enrollment is not None and enrollment["integrity_state"] == "CLEAR":
            enrollment["integrity_state"] = "FLAGGED"
            enrollment["integrity_incident_code"] = "PROCTOR_INCIDENT"
            touch(enrollment)
    return ok(derive.ser_proctor_session(session))


@bp.post("/proctor-sessions/<proctor_session_id>/no-show")
@endpoint("PlacementCoordinator")
def no_show_proctor_session(ctx, proctor_session_id):
    session = get_proctor_session(proctor_session_id)
    scope_center(ctx, store.stations[session["proctor_station_id"]]["center_id"])
    b = v.body()
    note = v.opt_str(b, "no_show_note", 1, None)
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "only a SCHEDULED session may be marked as a no-show")
    session["status"] = "NO_SHOW"
    if note is not None:
        session["no_show_note"] = note
    touch(session)
    return ok(derive.ser_proctor_session(session))
