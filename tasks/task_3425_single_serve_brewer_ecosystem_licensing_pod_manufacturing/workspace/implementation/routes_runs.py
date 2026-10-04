"""Production runs: reserve windows against filling-line capacity, drive the
RESERVED -> IN_PROGRESS -> COMPLETED / CANCELLED lifecycle."""
from datetime import timedelta
from flask import Blueprint, request

from store import db, get_clock
from helpers import (
    ApiError, body, created, find, fmt_dt, init_common, list_ok, need, ok,
    parse_dt_val, require_roles, touch, v_enum, v_int, v_str,
)
from calc import window_days
from serializers import run_out

bp = Blueprint("runs", __name__)

RUN_TARGETS = ("IN_PROGRESS", "COMPLETED", "CANCELLED")

_DECLARED = {
    ("RESERVED", "IN_PROGRESS"), ("IN_PROGRESS", "COMPLETED"),
    ("RESERVED", "CANCELLED"),
}

_NON_TERMINAL = ("RESERVED", "IN_PROGRESS")


def _open_runs_on_line(line_id):
    return [r for r in db["runs"].values()
            if r["line_id"] == line_id and r["status"] in _NON_TERMINAL]


@bp.post("/production-runs")
@require_roles("ProductionPlanner")
def create_run():
    b = body()
    raw_line = b.get("line_id")
    raw_variety = b.get("variety_id")
    if isinstance(raw_line, str) and raw_line not in db["lines"]:
        raise ApiError("ERR_NOT_FOUND", 404, "FillingLine not found: %s" % raw_line)
    if isinstance(raw_variety, str) and raw_variety not in db["varieties"]:
        raise ApiError("ERR_NOT_FOUND", 404, "PodVariety not found: %s" % raw_variety)
    line_id = v_str(b, "line_id")
    variety_id = v_str(b, "variety_id")
    line = db["lines"][line_id]
    variety = db["varieties"][variety_id]
    ws = parse_dt_val(need(b, "window_start"))
    we = parse_dt_val(need(b, "window_end"))
    planned = v_int(b, "planned_units")
    # Window shape
    if not ws < we:
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "window_start must strictly precede window_end")
    # Temporal window
    if ws < get_clock():
        raise ApiError("ERR_WINDOW_IN_PAST", 422,
                       "window_start is before the logical clock")
    # Conflicts: half-open overlap, then changeover buffer
    existing = _open_runs_on_line(line_id)
    for r in existing:
        if ws < r["_we"] and r["_ws"] < we:
            raise ApiError("ERR_LINE_WINDOW_CONFLICT", 409,
                           "Half-open overlap with an existing run on this line")
    for r in existing:
        rv = db["varieties"][r["variety_id"]]
        if rv["roast_level"] == variety["roast_level"] and \
                rv["material"] == variety["material"]:
            continue
        gap = timedelta(hours=line["changeover_hours"])
        if ws >= r["_we"]:
            if ws < r["_we"] + gap:
                raise ApiError("ERR_CHANGEOVER_BUFFER_VIOLATION", 409,
                               "Insufficient changeover gap after the earlier run")
        elif r["_ws"] >= we:
            if r["_ws"] < we + gap:
                raise ApiError("ERR_CHANGEOVER_BUFFER_VIOLATION", 409,
                               "Insufficient changeover gap before the later run")
    # Line capability
    if not (line["supported_roast"] == "UNIVERSAL"
            or line["supported_roast"] == variety["roast_level"]):
        raise ApiError("ERR_LINE_INCOMPATIBLE", 422,
                       "Line cannot run the variety's roast_level")
    if variety["flavor_family"] == "FLAVORED" and not line["supports_flavored"]:
        raise ApiError("ERR_LINE_INCOMPATIBLE", 422,
                       "Line cannot fill FLAVORED varieties")
    if not (line["material_capability"] == "BOTH"
            or line["material_capability"] == variety["material"]):
        raise ApiError("ERR_LINE_INCOMPATIBLE", 422,
                       "Line cannot run the variety's material")
    # Referenced-entity state
    if variety["status"] != "ACTIVE":
        raise ApiError("ERR_VARIETY_NOT_ACTIVE", 409,
                       "Production runs require an ACTIVE variety")
    # Capacity
    days = window_days(ws, we)
    if planned < 1 or planned > line["capacity_pods_per_day"] * days:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409,
                       "planned_units exceed line capacity for the window")
    run = init_common({
        "line_id": line_id, "variety_id": variety_id,
        "window_start": fmt_dt(ws), "window_end": fmt_dt(we),
        "planned_units": planned, "actual_units": None, "status": "RESERVED",
        "_ws": ws, "_we": we,
    })
    db["runs"][run["id"]] = run
    return created(run_out(run))


@bp.get("/production-runs/<rid>")
@require_roles("ProductionPlanner", "OperationsDirector")
def get_run(rid):
    return ok(run_out(find("runs", rid)))


@bp.get("/production-runs")
@require_roles("ProductionPlanner", "OperationsDirector")
def list_runs():
    items = list(db["runs"].values())
    f_line = request.args.get("line_id")
    f_variety = request.args.get("variety_id")
    f_status = request.args.get("status")
    if f_line is not None:
        items = [r for r in items if r["line_id"] == f_line]
    if f_variety is not None:
        items = [r for r in items if r["variety_id"] == f_variety]
    if f_status is not None:
        items = [r for r in items if r["status"] == f_status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_ok(items, run_out)


@bp.post("/production-runs/<rid>/transition")
@require_roles("ProductionPlanner")
def transition_run(rid):
    run = find("runs", rid)
    b = body()
    target = v_enum(b, "target_state", RUN_TARGETS)
    actual = None
    if target == "COMPLETED":
        actual = v_int(b, "actual_units")
    if (run["status"], target) not in _DECLARED:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "No declared transition from %s to %s" % (run["status"], target))
    if target == "IN_PROGRESS":
        clock = get_clock()
        if not (run["_ws"] <= clock < run["_we"]):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Run window is not open at the logical clock")
    if target == "COMPLETED":
        line = db["lines"][run["line_id"]]
        days = window_days(run["_ws"], run["_we"])
        if actual < 0 or actual > line["capacity_pods_per_day"] * days:
            raise ApiError("ERR_CAPACITY_EXCEEDED", 409,
                           "actual_units exceed line capacity for the window")
        run["actual_units"] = actual
    run["status"] = target
    touch(run)
    return ok(run_out(run))
