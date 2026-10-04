"""DesignJob endpoints — the retail design service (PRD 3.2)."""
from datetime import timedelta

from flask import Blueprint, request

from auth import get_body, require_roles
from db import bump, new_entity, store
from envelope import ok, paginate
from errors import api_error
from services import (REVISION_CAP, TRAVEL_BUFFER_MINUTES, base_lead_extremes,
                      create_order_entity, family_map, get_active_line,
                      price_items, recompute_credit)
from util import add_weeks, parse_dt, parse_week, week_of

bp = Blueprint("design", __name__)

READ_ROLES = ("RetailDesigner", "ProgramManager", "PlatformAdmin")


def serialize(job):
    return dict(job)


def designer_windows_conflict(designer_id, store_code, start, end, exclude_job_id=None):
    """PRD 3.2: per-designer windows are half-open [start, end); at the same
    store_code they may touch; across different store codes a 30-minute travel
    buffer is required."""
    buffer = timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    for job in store.design_jobs.values():
        if job["designer_user_id"] != designer_id:
            continue
        if exclude_job_id is not None and job["id"] == exclude_job_id:
            continue
        if job["status"] not in ("REQUESTED", "MEASURED"):
            continue
        other_start = parse_dt(job["measure_window_start"])
        other_end = parse_dt(job["measure_window_end"])
        if other_start is None or other_end is None:
            continue
        if job["store_code"] == store_code:
            if start < other_end and other_start < end:
                return True
        else:
            if not (end + buffer <= other_start or other_end + buffer <= start):
                return True
    return False


def validate_window(body):
    """Window presence (400), parseability (400), then shape vs the logical clock
    (ERR_MEASURE_WINDOW_INVALID). Returns (raw_start, raw_end, start_dt, end_dt)."""
    start_raw = body.get("measure_window_start")
    end_raw = body.get("measure_window_end")
    if start_raw is None or end_raw is None:
        raise api_error("ERR_INVALID_REQUEST",
                        "measure_window_start and measure_window_end are required")
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    if start_dt is None or end_dt is None:
        raise api_error("ERR_INVALID_REQUEST",
                        "measurement window fields must be ISO 8601 datetimes")
    if not (end_dt > start_dt) or start_dt < store.clock:
        raise api_error("ERR_MEASURE_WINDOW_INVALID",
                        "measure_window_end must be strictly after start and start "
                        "must not be earlier than the logical clock")
    return start_raw, end_raw, start_dt, end_dt


def validate_layout_lines(layout):
    if not isinstance(layout, list) or not layout:
        raise api_error("ERR_INVALID_REQUEST", "layout_lines must be a non-empty array")
    for li in layout:
        if not isinstance(li, dict):
            raise api_error("ERR_INVALID_REQUEST", "each layout line must be an object")
        if not isinstance(li.get("family_code"), str) or not li.get("family_code"):
            raise api_error("ERR_INVALID_REQUEST", "family_code is required on every layout line")
        if not isinstance(li.get("finish_code"), str) or not li.get("finish_code"):
            raise api_error("ERR_INVALID_REQUEST", "finish_code is required on every layout line")
        qty = li.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise api_error("ERR_INVALID_REQUEST", "quantity must be a positive integer")


def clean_layout(layout):
    return [{"family_code": li["family_code"],
             "finish_code": li["finish_code"],
             "quantity": li["quantity"]} for li in layout]


def check_families_covered(program, layout):
    line = get_active_line(program["id"])
    fmap = family_map(line) if line is not None else {}
    for li in layout:
        if li["family_code"] not in fmap:
            raise api_error("ERR_LINE_NOT_COVERED",
                            "family_code {} is not covered by the program's ACTIVE "
                            "line".format(li["family_code"]))


@bp.route("/cabinet/design-jobs", methods=["POST"])
def create_job():
    uid, _ = require_roles("RetailDesigner")
    body = get_body()
    account_id = body.get("account_id")
    program_id = body.get("program_id")
    if account_id is None or program_id is None:
        raise api_error("ERR_INVALID_REQUEST", "account_id and program_id are required")
    account = store.accounts.get(account_id)
    if account is None:
        raise api_error("ERR_NOT_FOUND", "account not found")
    program = store.programs.get(program_id)
    if program is None:
        raise api_error("ERR_NOT_FOUND", "program not found")
    if account["status"] != "ACTIVE":
        raise api_error("ERR_ACCOUNT_NOT_ACTIVE", "account is not ACTIVE")
    if account["channel"] != "RETAIL":
        raise api_error("ERR_CHANNEL_REQUIRES_DESIGN_JOB",
                        "design jobs are booked against RETAIL accounts")
    store_code = body.get("store_code")
    if store_code is None:
        raise api_error("ERR_INVALID_REQUEST", "store_code is required")
    if store_code not in account["store_codes"]:
        raise api_error("ERR_STORE_NOT_SERVICED",
                        "store_code is not an element of the account's store_codes")
    start_raw, end_raw, start_dt, end_dt = validate_window(body)
    if designer_windows_conflict(uid, store_code, start_dt, end_dt):
        raise api_error("ERR_DESIGNER_WINDOW_OVERLAP",
                        "measurement window overlaps another of this designer's jobs")
    job = new_entity()
    job.update({
        "account_id": account_id,
        "program_id": program_id,
        "store_code": store_code,
        "designer_user_id": uid,
        "measure_window_start": start_raw,
        "measure_window_end": end_raw,
        "layout_lines": None,
        "status": "REQUESTED",
        "revision_count": 0,
        "quoted_total_cents": None,
        "quoted_line_id": None,
    })
    store.design_jobs[job["id"]] = job
    return ok(serialize(job), 201)


@bp.route("/cabinet/design-jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    require_roles(*READ_ROLES)
    job = store.design_jobs.get(job_id)
    if job is None:
        raise api_error("ERR_NOT_FOUND", "design job not found")
    return ok(serialize(job))


@bp.route("/cabinet/design-jobs", methods=["GET"])
def list_jobs():
    require_roles(*READ_ROLES)
    account_id = request.args.get("account_id")
    program_id = request.args.get("program_id")
    quoted_line_id = request.args.get("quoted_line_id")
    designer_user_id = request.args.get("designer_user_id")
    status = request.args.get("status")
    items = [j for j in store.design_jobs.values()
             if (account_id is None or j["account_id"] == account_id)
             and (program_id is None or j["program_id"] == program_id)
             and (quoted_line_id is None or j["quoted_line_id"] == quoted_line_id)
             and (designer_user_id is None or j["designer_user_id"] == designer_user_id)
             and (status is None or j["status"] == status)]
    items = sorted(items, key=lambda j: j["created_at"])
    page, meta = paginate([serialize(j) for j in items])
    return ok(page, 200, meta)


@bp.route("/cabinet/design-jobs/<job_id>/transition", methods=["POST"])
def transition_job(job_id):
    uid, _ = require_roles("RetailDesigner")
    job = store.design_jobs.get(job_id)
    if job is None:
        raise api_error("ERR_NOT_FOUND", "design job not found")
    if uid != job["designer_user_id"]:
        raise api_error("ERR_FORBIDDEN",
                        "only the owning designer may transition this job")
    body = get_body()
    to_status = body.get("to_status")
    if to_status is None:
        raise api_error("ERR_INVALID_REQUEST", "to_status is required")
    current = job["status"]
    legal_targets = {
        "REQUESTED": {"MEASURED", "CANCELLED"},
        "MEASURED": {"LAYOUT_READY", "CANCELLED"},
        "LAYOUT_READY": {"QUOTED", "MEASURED", "CANCELLED"},
        "QUOTED": {"LAYOUT_READY", "MEASURED", "CANCELLED"},
    }
    if to_status not in legal_targets.get(current, set()):
        raise api_error("ERR_INVALID_STATE",
                        "cannot move design job from {} to {}".format(current, to_status))
    program = store.programs[job["program_id"]]

    if to_status == "MEASURED" and current == "REQUESTED":
        pass
    elif to_status == "LAYOUT_READY" and current == "MEASURED":
        layout = body.get("layout_lines")
        validate_layout_lines(layout)
        check_families_covered(program, layout)
        job["layout_lines"] = clean_layout(layout)
    elif to_status == "QUOTED" and current == "LAYOUT_READY":
        account = store.accounts[job["account_id"]]
        items = [{"family_code": li["family_code"], "quantity": li["quantity"]}
                 for li in job["layout_lines"]]
        total, _unit_nets, line = price_items(account, program, items)
        job["quoted_total_cents"] = total
        job["quoted_line_id"] = line["id"]
    elif to_status == "LAYOUT_READY" and current == "QUOTED":
        # Backward revision: fresh layout_lines required; cap 3.
        layout = body.get("layout_lines")
        validate_layout_lines(layout)
        if job["revision_count"] >= REVISION_CAP:
            raise api_error("ERR_REVISION_LIMIT_EXCEEDED",
                            "backward revision cap of 3 reached")
        job["revision_count"] += 1
        job["quoted_total_cents"] = None
        job["layout_lines"] = clean_layout(layout)
    elif to_status == "MEASURED" and current in ("QUOTED", "LAYOUT_READY"):
        # Backward revision: fresh, valid, non-overlapping window; cap 3.
        start_raw, end_raw, start_dt, end_dt = validate_window(body)
        if designer_windows_conflict(uid, job["store_code"], start_dt, end_dt,
                                     exclude_job_id=job["id"]):
            raise api_error("ERR_DESIGNER_WINDOW_OVERLAP",
                            "revised window overlaps another of this designer's jobs")
        if job["revision_count"] >= REVISION_CAP:
            raise api_error("ERR_REVISION_LIMIT_EXCEEDED",
                            "backward revision cap of 3 reached")
        job["revision_count"] += 1
        if current == "QUOTED":
            job["quoted_total_cents"] = None
        if current == "LAYOUT_READY":
            job["layout_lines"] = None
        job["measure_window_start"] = start_raw
        job["measure_window_end"] = end_raw
    # CANCELLED carries no side effects beyond the status change.

    job["status"] = to_status
    bump(job)
    return ok(serialize(job))


@bp.route("/cabinet/design-jobs/<job_id>/convert", methods=["POST"])
def convert_job(job_id):
    uid, _ = require_roles("RetailDesigner")
    job = store.design_jobs.get(job_id)
    if job is None:
        raise api_error("ERR_NOT_FOUND", "design job not found")
    if uid != job["designer_user_id"]:
        raise api_error("ERR_FORBIDDEN",
                        "only the owning designer may convert this job")
    if job["status"] != "QUOTED":
        raise api_error("ERR_INVALID_STATE", "only a QUOTED design job can be converted")
    account = store.accounts[job["account_id"]]
    if account["status"] != "ACTIVE":
        raise api_error("ERR_ACCOUNT_NOT_ACTIVE", "account is not ACTIVE")
    program = store.programs[job["program_id"]]
    if program["status"] not in ("ACTIVE", "TRANSITIONING"):
        raise api_error("ERR_PROGRAM_NOT_ACTIVE",
                        "program must be ACTIVE or TRANSITIONING")
    quoted_line = store.lines.get(job["quoted_line_id"] or "")
    if quoted_line is None or quoted_line["status"] != "ACTIVE":
        raise api_error("ERR_QUOTE_STALE",
                        "the line the quote was priced against is no longer ACTIVE")
    body = get_body()
    destination_type = body.get("destination_type")
    if destination_type not in ("JOB_SITE", "STORE"):
        raise api_error("ERR_INVALID_REQUEST", "destination_type must be JOB_SITE or STORE")
    store_code = None
    jobsite_address = None
    if destination_type == "STORE":
        store_code = body.get("store_code")
        if store_code is None:
            raise api_error("ERR_INVALID_REQUEST",
                            "store_code is required for STORE destinations")
        if store_code not in account["store_codes"]:
            raise api_error("ERR_STORE_NOT_SERVICED",
                            "store_code is not an element of the account's store_codes")
    else:
        jobsite_address = body.get("jobsite_address")
        if jobsite_address is None:
            raise api_error("ERR_INVALID_REQUEST",
                            "jobsite_address is required for JOB_SITE destinations")
    requested_week = body.get("requested_delivery_week")
    if parse_week(requested_week) is None:
        raise api_error("ERR_INVALID_REQUEST",
                        "requested_delivery_week must be an ISO week 'YYYY-Www'")
    family_codes = [li["family_code"] for li in job["layout_lines"]]
    min_lead, _max_lead = base_lead_extremes(quoted_line, family_codes)
    if parse_week(add_weeks(requested_week, -min_lead)) < parse_week(week_of(store.clock)):
        raise api_error("ERR_DELIVERY_WEEK_INVALID",
                        "requested_delivery_week minus the smallest base lead lands "
                        "before the current week")
    order = create_order_entity(account, program, job["layout_lines"],
                                destination_type, store_code, jobsite_address,
                                requested_week, job["id"])
    job["status"] = "CONVERTED"
    bump(job)
    recompute_credit(account["id"])
    return ok(order, 201)
