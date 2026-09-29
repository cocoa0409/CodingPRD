"""External reviewers, site-visit logistics and reviewer reports
(PRD 3.4 and 3.5)."""

from flask import Blueprint

import derive
import envelope
import filters
import serial
import valid
from errors import ApiError
from guards import (CHAIR, COORD, PROVOST, REVIEWER, begin, program_of_cycle,
                    program_of_visit)
from store import UTC, by_created, db, new_row, now, touch
from datetime import timedelta

bp = Blueprint("reviewers", __name__)

RECOMMENDATIONS = ("CONTINUE", "IMPROVE", "CONSOLIDATE", "DISCONTINUE")
VISIT_STATES_BLOCKING_TRAVEL = ("SCHEDULED", "COMPLETED")


# --------------------------------------------------------------------------
# reviewer registry
# --------------------------------------------------------------------------

@bp.route("/provost/external-reviewers", methods=["POST"])
def create_reviewer():
    ctx = begin((COORD,))
    body = ctx.require_object_body()
    full_name = valid.req_str(body, "full_name", 1, 120)
    institution = valid.req_str(body, "institution", 1, 120)
    specialty = valid.req_str(body, "specialty_code", 2, 20)
    conflicts = valid.code_array(body, "conflict_program_codes", 4, 12,
                                 allow_empty=True)
    buffer_hours = valid.opt_int(body, "travel_buffer_hours", 0, 168, default=48)

    row = new_row()
    row.update({
        "full_name": full_name,
        "institution": institution,
        "specialty_code": specialty,
        "conflict_program_codes": conflicts,
        "travel_buffer_hours": buffer_hours,
    })
    db.reviewers[row["id"]] = row
    return envelope.created(serial.reviewer(row))


# --------------------------------------------------------------------------
# two interval geometries (PRD 3.4)
# --------------------------------------------------------------------------

def _day_span(visit):
    start = visit["window_start_at"].astimezone(UTC).date()
    end = visit["window_end_at"].astimezone(UTC).date()
    return start, end


def _days_between(start, end):
    out = []
    cursor = start
    while cursor <= end:
        out.append(cursor)
        cursor = cursor + timedelta(days=1)
    return out


def _travel_conflict(reviewer, start, end):
    buffer_hours = timedelta(hours=reviewer["travel_buffer_hours"])
    for other in db.visits.values():
        if other["reviewer_id"] != reviewer["id"]:
            continue
        if other["state"] not in VISIT_STATES_BLOCKING_TRAVEL:
            continue
        low = other["window_start_at"] - buffer_hours
        high = other["window_end_at"] + buffer_hours
        if start < high and low < end:
            return True
    return False


def _capacity_exceeded(program, start, end):
    program_visits = []
    for other in db.visits.values():
        if other["state"] == "REPORTED":
            continue
        parent = program_of_visit(other)
        if parent is not None and parent["id"] == program["id"]:
            program_visits.append(other)
    spans = [_day_span(v) for v in program_visits]
    for day in _days_between(start, end):
        count = 1
        for span_start, span_end in spans:
            if span_start <= day <= span_end:
                count += 1
        if count > program["host_capacity_per_day"]:
            return True
    return False


# --------------------------------------------------------------------------
# visit scheduling
# --------------------------------------------------------------------------

@bp.route("/provost/reviewer-visits", methods=["POST"])
def create_visit():
    ctx = begin((COORD,))

    # check 8: body foreign keys, in the order the payload declares them
    cycle = None
    reviewer = None
    if ctx.body is not None and ctx.body.get("cycle_id") is not None:
        supplied = ctx.body.get("cycle_id")
        cycle = db.cycles.get(supplied) if isinstance(supplied, str) else None
        if cycle is None:
            raise ApiError("ERR_CYCLE_NOT_FOUND")
    if ctx.body is not None and ctx.body.get("reviewer_id") is not None:
        supplied = ctx.body.get("reviewer_id")
        reviewer = db.reviewers.get(supplied) if isinstance(supplied, str) else None
        if reviewer is None:
            raise ApiError("ERR_REVIEWER_NOT_FOUND")

    body = ctx.require_object_body()
    valid.req_str(body, "cycle_id", 1, 200)
    valid.req_str(body, "reviewer_id", 1, 200)
    start = valid.req_instant(body, "window_start_at")
    end = valid.req_instant(body, "window_end_at")
    if end <= start:
        valid.fail("window_end_at must be strictly after window_start_at.")

    program = program_of_cycle(cycle)
    ctx.not_terminal(program)

    if cycle["state"] not in ("SELF_STUDY_ACCEPTED", "VISIT_SCHEDULED"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    # check 21: conflict of interest
    if program is not None and program["code"] in reviewer["conflict_program_codes"]:
        raise ApiError("ERR_REVIEWER_CONFLICT_OF_INTEREST")

    # check 22: buffered half-open instant overlap
    if _travel_conflict(reviewer, start, end):
        raise ApiError("ERR_REVIEWER_WINDOW_CONFLICT")

    # check 23: inclusive calendar-day host capacity
    span_start = start.astimezone(UTC).date()
    span_end = end.astimezone(UTC).date()
    if program is not None and _capacity_exceeded(program, span_start, span_end):
        raise ApiError("ERR_PROGRAM_HOST_CAPACITY_EXCEEDED")

    row = new_row()
    row.update({
        "cycle_id": cycle["id"],
        "reviewer_id": reviewer["id"],
        "window_start_at": start,
        "window_end_at": end,
        "state": "SCHEDULED",
        "completed_at": None,
    })
    db.visits[row["id"]] = row

    if cycle["state"] == "SELF_STUDY_ACCEPTED":
        cycle["state"] = "VISIT_SCHEDULED"
    touch(cycle)
    return envelope.created(serial.visit(row))


@bp.route("/provost/reviewer-visits", methods=["GET"])
def list_visits():
    begin((COORD, PROVOST, CHAIR, REVIEWER))
    rows = by_created(db.visits.values())
    rows = filters.apply_string(rows, "cycle_id", "cycle_id")
    rows = filters.apply_string(rows, "reviewer_id", "reviewer_id")
    rows = filters.apply_string(rows, "state", "state")
    return envelope.paginate(rows, serial.visit)


@bp.route("/provost/reviewer-visits/<vid>", methods=["GET"])
def get_visit(vid):
    ctx = begin((COORD, PROVOST, CHAIR, REVIEWER))
    visit = db.visits.get(vid)
    ctx.chair_owner(program_of_visit(visit))
    ctx.require(visit, "ERR_VISIT_NOT_FOUND")
    return envelope.ok(serial.visit(visit))


@bp.route("/provost/reviewer-visits/<vid>/complete", methods=["POST"])
def complete_visit(vid):
    ctx = begin((COORD,))
    visit = db.visits.get(vid)
    ctx.require(visit, "ERR_VISIT_NOT_FOUND")

    ctx.not_terminal(program_of_visit(visit))

    if visit["state"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_NOT_SCHEDULED")
    if now() < visit["window_end_at"]:
        raise ApiError("ERR_VISIT_WINDOW_NOT_ELAPSED")

    visit["state"] = "COMPLETED"
    visit["completed_at"] = now()
    touch(visit)

    cycle = db.cycles.get(visit["cycle_id"])
    if cycle is not None and cycle["state"] == "VISIT_SCHEDULED":
        siblings = [v for v in derive.visits_of(cycle["id"])
                    if v["id"] != visit["id"]]
        if all(v["state"] in ("COMPLETED", "REPORTED") for v in siblings):
            cycle["state"] = "VISIT_COMPLETED"
            touch(cycle)
    return envelope.ok(serial.visit(visit))


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------

@bp.route("/provost/reviewer-visits/<vid>/reports", methods=["POST"])
def file_report(vid):
    ctx = begin((REVIEWER,))
    visit = db.visits.get(vid)
    ctx.reviewer_owner(visit)
    ctx.require(visit, "ERR_VISIT_NOT_FOUND")

    body = ctx.require_object_body()
    recommendation = valid.req_enum(body, "recommendation", RECOMMENDATIONS)
    findings = valid.code_array(body, "finding_codes", 1, 20,
                                allow_empty=False, required=True)
    narrative = valid.req_str(body, "narrative", 1, 20000)

    ctx.not_terminal(program_of_visit(visit))

    cycle = db.cycles.get(visit["cycle_id"])
    existing = derive.reports_of(vid)
    if not existing:
        if visit["state"] != "COMPLETED":
            raise ApiError("ERR_VISIT_NOT_SCHEDULED")
    else:
        if cycle is None or cycle["state"] != "ADDENDUM_REQUESTED":
            raise ApiError("ERR_REPORT_ALREADY_FILED")

    row = new_row(versioned=False)
    row.update({
        "visit_id": vid,
        "recommendation": recommendation,
        "finding_codes": findings,
        "narrative": narrative,
        "sequence_number": len(existing) + 1,
        "filed_at": now(),
    })
    db.reports[row["id"]] = row

    if not existing:
        visit["state"] = "REPORTED"
        touch(visit)
        if cycle is not None and cycle["state"] == "VISIT_COMPLETED":
            cycle["state"] = "REPORT_RECEIVED"
            touch(cycle)
    else:
        touch(visit)
        cycle["state"] = "REPORT_RECEIVED"
        cycle["response_concurrence"] = None
        cycle["response_text"] = None
        cycle["disputed_finding_codes"] = []
        touch(cycle)
    return envelope.created(serial.report(row))


@bp.route("/provost/reviewer-visits/<vid>/reports", methods=["GET"])
def list_reports(vid):
    ctx = begin((COORD, PROVOST, CHAIR, REVIEWER))
    visit = db.visits.get(vid)
    ctx.chair_owner(program_of_visit(visit))
    ctx.reviewer_owner(visit)
    ctx.require(visit, "ERR_VISIT_NOT_FOUND")
    rows = derive.reports_of(vid)
    return envelope.paginate(rows, serial.report)
