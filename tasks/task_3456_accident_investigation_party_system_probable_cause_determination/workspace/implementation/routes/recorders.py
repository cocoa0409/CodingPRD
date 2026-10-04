"""Recorder packages and lab-bench readout sessions (PRD 3.6).

POST /recorders                              RecorderCustodian
GET  /recorders                              all roles
GET  /recorders/{id}                         all roles
POST /recorders/{id}/readout-sessions        RecorderCustodian
"""

from flask import Blueprint, request

import clock
import db
import domain
from auth import get_context, require_roles
from constants import RECORDER_CONDITIONS, RECORDER_TYPES, ROLES
from envelope import ok_list, ok_object, paginate, parse_pagination
from errors import api_error
from serializers import recorder_public
from validate import get_body, req_enum, req_str

bp = Blueprint("recorders", __name__)


def _req_window(body, name):
    value = req_str(body, name)
    parsed = clock.parse_iso(value)
    if parsed is None:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "field '%s' must be an ISO 8601 UTC timestamp" % name,
        )
    return value, parsed


@bp.route("/recorders", methods=["POST"])
def create_recorder():
    _user_id, role = get_context()
    require_roles(role, ("RecorderCustodian",))
    body = get_body()
    investigation_id = req_str(body, "investigation_id")
    recorder_type = req_enum(body, "recorder_type", RECORDER_TYPES)
    condition = req_enum(body, "condition", RECORDER_CONDITIONS)
    investigation = domain.get_investigation(investigation_id)

    recorder = db.add(
        "recorders",
        {
            "investigation_id": investigation["id"],
            "recorder_type": recorder_type,
            "condition": condition,
            "status": "SECURED",
            "readout_sessions": [],
        },
    )
    return ok_object(recorder_public(recorder), status=201)


@bp.route("/recorders", methods=["GET"])
def list_recorders():
    _user_id, role = get_context()
    require_roles(role, ROLES)
    limit, offset = parse_pagination(request.args)
    items = db.all_of("recorders")
    for recorder in items:
        domain.refresh_recorder(recorder)
    investigation_id = request.args.get("investigation_id")
    if investigation_id is not None:
        items = [
            r for r in items if r["investigation_id"] == investigation_id
        ]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([recorder_public(r) for r in page], limit, offset, total)


@bp.route("/recorders/<recorder_id>", methods=["GET"])
def get_recorder(recorder_id):
    _user_id, role = get_context()
    require_roles(role, ROLES)
    recorder = domain.get_recorder(recorder_id)
    return ok_object(recorder_public(recorder), status=200)


@bp.route("/recorders/<recorder_id>/readout-sessions", methods=["POST"])
def schedule_readout_session(recorder_id):
    _user_id, role = get_context()
    require_roles(role, ("RecorderCustodian",))
    recorder = domain.get_recorder(recorder_id)
    domain.refresh_recorder(recorder)

    body = get_body()
    bench_id = req_str(body, "bench_id")
    window_start, start_dt = _req_window(body, "window_start_utc")
    window_end, end_dt = _req_window(body, "window_end_utc")

    if recorder["status"] not in ("SECURED", "IN_READOUT"):
        raise api_error(
            "ERR_RECORDER_STATE_INVALID",
            "readout sessions require recorder status SECURED or IN_READOUT",
        )

    now = clock.clock_dt()
    if now is None or start_dt <= now:
        raise api_error(
            "ERR_WINDOW_IN_PAST",
            "window_start_utc must lie strictly after the current logical "
            "clock",
        )
    if end_dt <= start_dt:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "window_end_utc must lie strictly after window_start_utc",
        )

    # Half-open [start, end) windows on the same bench must not overlap any
    # other SCHEDULED session on that bench; touching endpoints are allowed.
    for other in db.store["recorders"].values():
        for session in other["readout_sessions"]:
            if session["bench_id"] != bench_id:
                continue
            domain.refresh_session(session)
            if session["status"] != "SCHEDULED":
                continue
            other_start = clock.parse_iso(session["window_start_utc"])
            other_end = clock.parse_iso(session["window_end_utc"])
            if other_start is None or other_end is None:
                continue
            if domain.windows_overlap(start_dt, end_dt, other_start, other_end):
                raise api_error(
                    "ERR_BENCH_WINDOW_CONFLICT",
                    "the requested window overlaps another SCHEDULED session "
                    "on bench %s" % bench_id,
                )

    session = {
        "session_id": db.new_id(),
        "bench_id": bench_id,
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "status": "SCHEDULED",
    }
    recorder["readout_sessions"].append(session)
    if recorder["status"] == "SECURED":
        recorder["status"] = "IN_READOUT"
    db.touch(recorder)
    return ok_object(recorder_public(recorder), status=201)
