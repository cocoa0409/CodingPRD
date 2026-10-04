"""Coverage decisions and the stringer-hour budget (PRD §3.2)."""
from flask import Blueprint, request

from auth import require_roles, body
from envelope import ok_object, paginate
from errors import raise_err
from loaders import (
    get_event, get_contest, get_coverage, require_posture, versioned_record, touch,
)
from serializers import coverage_json
from store import db
from util import is_int, parse_date

bp = Blueprint("coverage", __name__)

COVERAGE_ROLES = ("ElectionOpsAdmin", "CoveragePlanner")
COVERAGE_STATUSES = ("PROPOSED", "APPROVED", "DECLINED", "FUNDED")


def _intervals_intersect(s1, e1, s2, e2):
    """Closed-interval intersection: decisions sharing exactly one boundary
    day DO intersect (PRD §3.2)."""
    return s1 <= e2 and s2 <= e1


def _check_budget(event, decision):
    """Priority 19: sum of allocated hours over the event's decisions in
    {APPROVED, FUNDED} whose closed intervals intersect this decision's, plus
    this decision's own hours, must not exceed the budget. The decision under
    review never counts itself twice."""
    total = decision["allocated_stringer_hours"]
    for d in db["coverages"].values():
        if d["id"] == decision["id"] or d["event_id"] != event["id"]:
            continue
        if d["status"] not in ("APPROVED", "FUNDED"):
            continue
        if _intervals_intersect(
            d["coverage_start"], d["coverage_end"],
            decision["coverage_start"], decision["coverage_end"],
        ):
            total += d["allocated_stringer_hours"]
    if total > event["total_stringer_hour_budget"]:
        raise_err(
            "ERR_COVERAGE_BUDGET_EXCEEDED",
            "Aggregate intersecting coverage hours would exceed the budget",
        )


@bp.post("/election-events/<rid>/coverage-decisions")
def create_coverage(rid):
    require_roles("CoveragePlanner")
    event = get_event(rid)
    require_posture(event, "SETUP", "CANDIDATES_LOCKED")
    data = body()
    for f in ("contest_id", "allocated_stringer_hours", "coverage_start", "coverage_end"):
        if f not in data or data[f] is None:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    contest = db["contests"].get(data["contest_id"])
    if contest is None:
        raise_err("ERR_CONTEST_NOT_FOUND", "Contest id does not resolve")
    # Priority 10: cross-event reference.
    if contest["event_id"] != event["id"]:
        raise_err("ERR_CROSS_EVENT_REFERENCE", "Contest belongs to another event")
    start = parse_date(data["coverage_start"])
    end = parse_date(data["coverage_end"])
    if start is None or end is None:
        raise_err("ERR_INVALID_REQUEST", "coverage_start/coverage_end must be ISO dates")
    # Priority 13: interval well-formedness (closed interval).
    if start > end:
        raise_err("ERR_INVALID_REQUEST", "coverage_start must not fall after coverage_end")
    if not is_int(data["allocated_stringer_hours"]) or data["allocated_stringer_hours"] < 1:
        raise_err("ERR_INVALID_REQUEST", "allocated_stringer_hours must be an integer >= 1")
    rationale = data.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        raise_err("ERR_INVALID_REQUEST", "rationale must be a string")

    rec = versioned_record()
    rec.update({
        "event_id": event["id"],
        "contest_id": contest["id"],
        "allocated_stringer_hours": data["allocated_stringer_hours"],
        "coverage_start": data["coverage_start"].strip(),
        "coverage_end": data["coverage_end"].strip(),
        "rationale": rationale,
        "status": "PROPOSED",
    })
    db["coverages"][rec["id"]] = rec
    return ok_object(coverage_json(rec), 201)


@bp.get("/election-events/<rid>/coverage-decisions")
def list_coverage_of_event(rid):
    require_roles(*COVERAGE_ROLES)
    event = get_event(rid)
    rows = [d for d in db["coverages"].values() if d["event_id"] == event["id"]]
    status = request.args.get("status")
    if status is not None:
        if status not in COVERAGE_STATUSES:
            raise_err("ERR_INVALID_REQUEST", "status filter out of range")
        rows = [d for d in rows if d["status"] == status]
    return paginate(rows, coverage_json)


@bp.get("/contests/<rid>/coverage-decisions")
def list_coverage_of_contest(rid):
    require_roles(*COVERAGE_ROLES)
    contest = get_contest(rid)
    rows = [d for d in db["coverages"].values() if d["contest_id"] == contest["id"]]
    return paginate(rows, coverage_json)


@bp.post("/coverage-decisions/<rid>/review")
def review_coverage(rid):
    require_roles("ElectionOpsAdmin")
    decision = get_coverage(rid)
    event = get_event(decision["event_id"])
    data = body()
    action = data.get("decision")
    if action not in ("APPROVE", "DECLINE", "FUND"):
        raise_err("ERR_INVALID_REQUEST", "decision must be APPROVE, DECLINE or FUND")
    if action == "APPROVE":
        if decision["status"] != "PROPOSED":
            raise_err("ERR_INVALID_STATE", "APPROVE requires status PROPOSED")
        _check_budget(event, decision)
        decision["status"] = "APPROVED"
    elif action == "DECLINE":
        if decision["status"] != "PROPOSED":
            raise_err("ERR_INVALID_STATE", "DECLINE requires status PROPOSED")
        decision["status"] = "DECLINED"
    else:  # FUND — a second, separate gate re-running the same budget check.
        if decision["status"] != "APPROVED":
            raise_err("ERR_INVALID_STATE", "FUND requires status APPROVED")
        _check_budget(event, decision)
        decision["status"] = "FUNDED"
    touch(decision)
    return ok_object(coverage_json(decision))


@bp.post("/coverage-decisions/<rid>/revise")
def revise_coverage(rid):
    require_roles("CoveragePlanner")
    decision = get_coverage(rid)
    if decision["status"] != "DECLINED":
        raise_err("ERR_INVALID_STATE", "Revise requires status DECLINED")
    data = body()
    hours = data.get("allocated_stringer_hours")
    if hours is not None:
        if not is_int(hours) or hours < 1:
            raise_err("ERR_INVALID_REQUEST", "allocated_stringer_hours must be an integer >= 1")
    start_raw = data.get("coverage_start")
    end_raw = data.get("coverage_end")
    new_start = decision["coverage_start"] if start_raw is None else start_raw
    new_end = decision["coverage_end"] if end_raw is None else end_raw
    sd = parse_date(new_start)
    ed = parse_date(new_end)
    if sd is None or ed is None:
        raise_err("ERR_INVALID_REQUEST", "coverage dates must be ISO dates")
    # The interval well-formedness rule applies to the revised dates exactly
    # as at creation (PRD §3.2).
    if sd > ed:
        raise_err("ERR_INVALID_REQUEST", "coverage_start must not fall after coverage_end")
    if hours is not None:
        decision["allocated_stringer_hours"] = hours
    decision["coverage_start"] = new_start.strip() if isinstance(new_start, str) else new_start
    decision["coverage_end"] = new_end.strip() if isinstance(new_end, str) else new_end
    decision["status"] = "PROPOSED"
    touch(decision)
    return ok_object(coverage_json(decision))
