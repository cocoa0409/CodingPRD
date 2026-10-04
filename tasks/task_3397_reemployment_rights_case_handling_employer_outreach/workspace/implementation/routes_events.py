"""Outreach events (with venue double-booking) and the sector-trend report."""
from datetime import timedelta

from flask import Blueprint, request

from auth import require_role
from errors import ApiError
from helpers import (
    body_json, req_str, req_enum, req_dt,
    get_event, ser_event, touch,
    EVENT_TOPICS, EVENT_STATUSES, SECTORS, VENUE_BUFFER_MINUTES,
)
from store import db
from util import now, new_id, success, parse_dt, fmt_dt

bp = Blueprint("events", __name__)


@bp.route("/reemployment/outreach-events", methods=["POST"])
def create_event():
    require_role("ProgramCoordinator")
    body = body_json()
    title = req_str(body, "title")
    venue = req_str(body, "venue")
    starts_at = req_dt(body, "starts_at")
    ends_at = req_dt(body, "ends_at")
    topic = req_enum(body, "topic", EVENT_TOPICS)
    if ends_at <= starts_at:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "ends_at must be strictly after starts_at",
        )
    # Venue double-booking: closed intervals including a 60-minute teardown
    # buffer after each event; events that merely touch count as overlapping;
    # CANCELLED events are excluded from the comparison set.
    buf = timedelta(minutes=VENUE_BUFFER_MINUTES)
    for e in db.events.values():
        if e["venue"] != venue or e["status"] == "CANCELLED":
            continue
        if starts_at <= e["ends_at"] + buf and e["starts_at"] <= ends_at + buf:
            raise ApiError(
                "ERR_VENUE_DOUBLE_BOOKED", 422,
                "Venue %s is already booked for an overlapping event" % venue,
            )
    eid = new_id()
    t = now()
    e = {
        "id": eid, "title": title, "venue": venue,
        "starts_at": starts_at, "ends_at": ends_at, "topic": topic,
        "status": "PLANNED",
        "created_at": t, "updated_at": t, "version": 1, "_seq": db.next_seq(),
    }
    db.events[eid] = e
    return success(ser_event(e), "object", 201)


@bp.route("/reemployment/outreach-events/<eid>/state", methods=["POST"])
def event_state(eid):
    require_role("ProgramCoordinator")
    body = body_json()
    to_status = req_enum(body, "to_status", EVENT_STATUSES)
    e = get_event(eid)
    frm = e["status"]
    if to_status == "OPEN":
        if frm != "PLANNED":
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition event from %s to OPEN" % frm,
            )
        e["status"] = "OPEN"
    elif to_status == "CONCLUDED":
        if frm != "OPEN":
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition event from %s to CONCLUDED" % frm,
            )
        if now() < e["ends_at"]:
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot conclude an event before its ends_at",
            )
        e["status"] = "CONCLUDED"
    elif to_status == "CANCELLED":
        if frm not in ("PLANNED", "OPEN"):
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition event from %s to CANCELLED" % frm,
            )
        e["status"] = "CANCELLED"
    else:
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "No transition to %s exists" % to_status,
        )
    touch(e)
    return success(ser_event(e))


@bp.route("/reemployment/reports/sector-trends", methods=["GET"])
def sector_trends():
    require_role("ProgramCoordinator")
    args = request.args
    sector = args.get("sector")
    if sector is None or sector not in SECTORS:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "sector must be one of %s" % ", ".join(SECTORS),
        )
    period_start = parse_dt(args.get("period_start"))
    period_end = parse_dt(args.get("period_end"))
    if period_start is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "period_start must be an ISO-8601 datetime"
        )
    if period_end is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "period_end must be an ISO-8601 datetime"
        )
    if period_end <= period_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "period_end must be strictly after period_start",
        )
    # Half-open created_at window [period_start, period_end), sector matched
    # through the case's employer.
    window = []
    for c in db.cases.values():
        if not (period_start <= c["created_at"] < period_end):
            continue
        emp = db.employers.get(c["employer_id"])
        if emp is None or emp["sector"] != sector:
            continue
        window.append(c)
    total_cases = len(window)
    resolved_count = sum(1 for c in window if c["status"] == "RESOLVED_INFORMAL")
    per_employer = {}
    for c in window:
        per_employer[c["employer_id"]] = per_employer.get(c["employer_id"], 0) + 1
    repeat_employer_count = sum(1 for v in per_employer.values() if v >= 2)
    top_issue_type = None
    if window:
        counts = {}
        earliest = {}
        for c in window:
            it = c["issue_type"]
            counts[it] = counts.get(it, 0) + 1
            key = (c["created_at"], c["_seq"])
            if it not in earliest or key < earliest[it]:
                earliest[it] = key
        max_count = max(counts.values())
        tied = [it for it, v in counts.items() if v == max_count]
        # Tie-break: the tied issue type whose earliest-created case in the
        # window comes first wins.
        top_issue_type = min(tied, key=lambda it: earliest[it])
    return success({
        "sector": sector,
        "period_start": fmt_dt(period_start),
        "period_end": fmt_dt(period_end),
        "total_cases": total_cases,
        "repeat_employer_count": repeat_employer_count,
        "resolved_count": resolved_count,
        "top_issue_type": top_issue_type,
    })
