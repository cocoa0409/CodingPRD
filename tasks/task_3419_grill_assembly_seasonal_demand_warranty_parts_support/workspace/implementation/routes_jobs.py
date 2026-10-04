"""AssemblyJob request, scheduling and lifecycle (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import derive
from auth import authenticate, check_action_role, check_ownership, require_role
from constants import (
    JOB_TYPES,
    NO_SHOW_SUSPEND_THRESHOLD,
    TRAVEL_BUFFER_MINUTES,
)
from errors import api_error, not_found, validation
from serialize import job_out
from store import db, new_entity, touch
from util import get_body, ok, ok_list, opt_int, paginate, req_enum, require

bp = Blueprint("assembly_jobs", __name__, url_prefix="/grillops")

READ_ROLES = ("PlannerAdmin", "ServiceAgent", "Assembler", "ChannelRep")
ACTION_ROLES = {
    "ASSIGN": ("ServiceAgent",),
    "START": ("Assembler",),
    "COMPLETE": ("Assembler",),
    "CANCEL": ("ServiceAgent",),
    "NO_SHOW": ("ServiceAgent",),
}
VALID_FROM = {
    "ASSIGN": ("REQUESTED", "NO_SHOW"),
    "START": ("SCHEDULED",),
    "COMPLETE": ("IN_PROGRESS",),
    "CANCEL": ("REQUESTED", "SCHEDULED"),
    "NO_SHOW": ("SCHEDULED",),
}


@bp.post("/assembly-jobs")
def create_job():
    _, role = authenticate()
    require_role(role, ("ChannelRep", "ServiceAgent"))
    data = get_body()
    # rung 3: body-carried sale reference
    sale_id = require(data, "sale_id")
    sale = db.sales.get(sale_id)
    if sale is None:
        raise not_found("SALE")
    # rung 6: body
    job_type = req_enum(data, "job_type", JOB_TYPES)
    distance_mi = opt_int(data, "distance_mi", 0)
    if distance_mi < 0:
        raise validation("distance_mi must be >= 0")
    channel = db.channels.get(sale["channel_account_id"])
    subsidy_bp = channel["subsidy_bp"] if channel is not None else 0
    fee_cents = derive.calc_assembly_fee(job_type, distance_mi, subsidy_bp)
    job = new_entity({
        "sale_id": sale["id"],
        "assembler_id": None,
        "job_type": job_type,
        "distance_mi": distance_mi,
        "window_start": None,
        "window_end": None,
        "fee_cents": fee_cents,
        "status": "REQUESTED",
    })
    db.jobs[job["id"]] = job
    return ok(job_out(job), status=201)


@bp.get("/assembly-jobs/<job_id>")
def get_job(job_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    job = db.jobs.get(job_id)
    if job is None:
        raise not_found("JOB")
    return ok(job_out(job))


@bp.get("/assembly-jobs")
def list_jobs():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    items = list(db.jobs.values())
    for field in ("assembler_id", "sale_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            items = [j for j in items if j.get(field) == raw]
    page, total, limit, offset = paginate(items)
    return ok_list([job_out(j) for j in page], total, limit, offset)


def _overlaps(s1, e1, s2, e2):
    """Half-open [start, end) overlap; adjacency (end == start) is allowed."""
    return s1 < e2 and s2 < e1


def _assign(job, assembler, data):
    # rung 6: window well-formedness precedes the certification check
    raw_start = require(data, "window_start")
    raw_end = require(data, "window_end")
    try:
        window_start = clock.parse_iso(raw_start)
        window_end = clock.parse_iso(raw_end)
    except (ValueError, TypeError):
        raise validation("window_start and window_end must be ISO-8601 datetimes")
    if not window_end > window_start:
        raise validation("window_end must be strictly after window_start")
    # rung 7: the named assembler must be CERTIFIED
    if assembler["status"] != "CERTIFIED":
        raise api_error("ERR_ASSEMBLER_NOT_CERTIFIED", "assembler is not CERTIFIED")
    # rung 8a: same-sale active jobs, raw half-open window
    for other in db.jobs.values():
        if (
            other["sale_id"] == job["sale_id"]
            and other["id"] != job["id"]
            and other["status"] in ("SCHEDULED", "IN_PROGRESS")
            and other["window_start"] is not None
        ):
            if _overlaps(window_start, window_end,
                         clock.parse_iso(other["window_start"]),
                         clock.parse_iso(other["window_end"])):
                raise api_error("ERR_ASSEMBLY_WINDOW_CONFLICT", "another active job on this sale overlaps the requested window")
    # rung 8b: same-assembler active jobs; a NEW In-Home window is padded
    # by +/- TRAVEL_BUFFER_MINUTES before the test; retail jobs never pad
    pad = timedelta(minutes=TRAVEL_BUFFER_MINUTES) if job["job_type"] == "IN_HOME" else timedelta(0)
    padded_start = window_start - pad
    padded_end = window_end + pad
    for other in db.jobs.values():
        if (
            other["assembler_id"] == assembler["id"]
            and other["id"] != job["id"]
            and other["status"] in ("SCHEDULED", "IN_PROGRESS")
            and other["window_start"] is not None
        ):
            if _overlaps(padded_start, padded_end,
                         clock.parse_iso(other["window_start"]),
                         clock.parse_iso(other["window_end"])):
                raise api_error("ERR_ASSEMBLER_BUFFER_CONFLICT", "the assembler's schedule conflicts (travel buffer applied)")
    # rung 9: concurrency cap — reaching the cap is refused (exclusive boundary)
    derive.recompute_assembler(assembler)
    if assembler["active_job_count"] >= assembler["max_concurrent_jobs"]:
        raise api_error("ERR_MAX_CONCURRENT_JOBS", "assembler is at max_concurrent_jobs")
    job["assembler_id"] = assembler["id"]
    job["window_start"] = clock.iso_z(window_start)
    job["window_end"] = clock.iso_z(window_end)
    job["status"] = "SCHEDULED"
    touch(job)
    derive.recompute_assembler(assembler)  # active_job_count += 1 (derived)


def _auto_suspend_check(assembler):
    if (
        assembler["no_show_count"] >= NO_SHOW_SUSPEND_THRESHOLD
        and assembler["status"] == "CERTIFIED"
    ):
        assembler["status"] = "SUSPENDED"
        # cascade: every OTHER scheduled job returns to REQUESTED, unassigned
        for other in db.jobs.values():
            if other["assembler_id"] == assembler["id"] and other["status"] == "SCHEDULED":
                other["status"] = "REQUESTED"
                other["assembler_id"] = None
                other["window_start"] = None
                other["window_end"] = None
                touch(other)
        derive.recompute_assembler(assembler)
        touch(assembler)  # the auto-suspend transition itself


@bp.post("/assembly-jobs/<job_id>/transition")
def transition_job(job_id):
    user_id, role = authenticate()
    require_role(role, ("ServiceAgent", "Assembler"))
    job = db.jobs.get(job_id)
    if job is None:
        raise not_found("JOB")
    data = get_body()
    action = data.get("action")
    # rung 2 (action level) for known actions
    check_action_role(role, action, ACTION_ROLES)
    # rung 4: START / COMPLETE are ownership-scoped to the assigned assembler
    if action in ("START", "COMPLETE") and role == "Assembler":
        check_ownership(user_id, job["assembler_id"])
    # rung 6: action is a required enum field
    if action is None:
        raise validation("action is required")
    if action not in ACTION_ROLES:
        raise validation("action must be one of ASSIGN, START, COMPLETE, CANCEL, NO_SHOW")
    # rung 3 (body-carried reference): ASSIGN's assembler must exist
    assembler = None
    if action == "ASSIGN":
        assembler_id = require(data, "assembler_id")
        assembler = db.assemblers.get(assembler_id)
        if assembler is None:
            raise not_found("ASSEMBLER")
    # rung 5: valid-from state
    if job["status"] not in VALID_FROM[action]:
        raise api_error(
            "ERR_JOB_NOT_SCHEDULABLE",
            "action %s is not available from status %s" % (action, job["status"]),
        )

    if action == "ASSIGN":
        _assign(job, assembler, data)
    elif action == "START":
        job["status"] = "IN_PROGRESS"
        touch(job)
    elif action == "COMPLETE":
        job["status"] = "COMPLETED"
        touch(job)
        assembler = db.assemblers.get(job["assembler_id"])
        if assembler is not None:
            assembler["jobs_completed"] += 1
            assembler["completion_history"].append(clock.iso_z(clock.now()))
            derive.recompute_assembler(assembler)
            touch(assembler)
    elif action == "CANCEL":
        was_scheduled = job["status"] == "SCHEDULED"
        job["status"] = "CANCELLED"
        touch(job)
        if was_scheduled:
            assembler = db.assemblers.get(job["assembler_id"])
            if assembler is not None:
                derive.recompute_assembler(assembler)
                touch(assembler)
    elif action == "NO_SHOW":
        # hop 1: counters move; the job keeps its assembler_id for audit
        job["status"] = "NO_SHOW"
        touch(job)
        assembler = db.assemblers.get(job["assembler_id"])
        if assembler is not None:
            assembler["no_show_count"] += 1
            assembler["no_show_history"].append(clock.iso_z(clock.now()))
            derive.recompute_assembler(assembler)
            touch(assembler)
            # hops 2+3: auto-suspend at the threshold, then cascade
            _auto_suspend_check(assembler)
    return ok(job_out(job))
