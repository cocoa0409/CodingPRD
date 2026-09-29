"""Language-access reporting, the daily operations run and the clock (PRD 3.10)."""
from flask import Blueprint, request

import cascades
import derive
import serializers as S
from auth import require
from envelope import object_response
from errors import ApiError
from store import db, new_row, now, sort_created, today, touch
from util import day_start, fmt_date, fmt_dt, parse_date, parse_dt
from validation import body_of, date_field, datetime_field, str_field

bp = Blueprint("reports", __name__)

COVERING_STATUSES = ("CONFIRMED", "CHECKED_IN", "COMPLETED")


@bp.route("/unmet-need-reports", methods=["POST"])
def create_unmet_need_report():
    require("ProgramAdmin", "QualityReviewer")
    body = body_of(request)
    courthouse_id = str_field(body, "courthouse_id")
    period_start = date_field(body, "period_start")
    period_end = date_field(body, "period_end")
    if period_end <= period_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "period_end must be strictly after period_start.",
        )

    courthouse = derive.get_courthouse(courthouse_id)

    if day_start(period_end) > now():
        raise ApiError(
            "ERR_REPORT_PERIOD_INVALID",
            "The reporting window is not yet closed.",
        )
    if (period_end - period_start).days > derive.MAX_REPORT_SPAN_DAYS:
        raise ApiError(
            "ERR_REPORT_PERIOD_INVALID",
            "The reporting window may span at most 400 days.",
        )

    snapshot = derive.coverage_snapshot(courthouse["id"], period_start, period_end)
    row = new_row(common=False)
    row.update(
        {
            "courthouse_id": courthouse["id"],
            "period_start": fmt_date(period_start),
            "period_end": fmt_date(period_end),
        }
    )
    row.update(snapshot)
    db.unmet_need_reports[row["id"]] = row
    return object_response(S.unmet_need_report_out(row), 201)


@bp.route("/ops/daily-sweep", methods=["POST"])
def daily_sweep():
    require("ProgramAdmin")
    body_of(request)
    log = cascades.new_sweep_log()
    current_date = today()

    # Step one: credential expiry.
    for credential in sort_created(list(db.credentials.values())):
        if credential["status"] != "ACTIVE":
            continue
        expires_on = parse_date(credential["expires_on"])
        if expires_on is not None and expires_on < current_date:
            cascades.lapse_credential(credential, log)

    # Step two: sanction expiry, then reinstatement.
    for action in sort_created(list(db.disciplinary_actions.values())):
        if action["status"] != "IN_EFFECT":
            continue
        through = parse_date(action["effective_through"])
        if through is not None and through < current_date:
            action["status"] = "EXPIRED"
            touch(action)
            log["expired_action_ids"].append(action["id"])

    for interpreter in sort_created(list(db.interpreters.values())):
        if interpreter["roster_status"] != "SUSPENDED":
            continue
        remaining = [
            a
            for a in db.disciplinary_actions.values()
            if a["interpreter_id"] == interpreter["id"]
            and a["action_type"] == "SUSPENSION"
            and a["status"] == "IN_EFFECT"
        ]
        if remaining:
            continue
        interpreter["suspension_through"] = None
        interpreter["roster_status"] = (
            "ACTIVE" if derive.active_credentials_of(interpreter["id"]) else "INACTIVE"
        )
        touch(interpreter)
        log["reinstated_interpreter_ids"].append(interpreter["id"])

    # Step three: hearings that passed uncovered.
    hearings = sorted(
        db.hearings.values(),
        key=lambda h: (h["scheduled_start"], h["created_at"], h["_seq"]),
    )
    for hearing in hearings:
        if hearing["status"] != "SCHEDULED":
            continue
        if now() < parse_dt(hearing["scheduled_start"]):
            continue
        assignments = derive.assignments_of_hearing(hearing["id"])
        if any(a["service_status"] in COVERING_STATUSES for a in assignments):
            continue
        hearing["status"] = "UNMET"
        touch(hearing)
        log["unmet_hearing_ids"].append(hearing["id"])
        for assignment in assignments:
            if assignment["service_status"] == "PROPOSED":
                cascades.cancel_assignment(assignment, "COORDINATOR_CANCELLED", log)

    data = {"swept_at": fmt_dt(now())}
    data.update(log)
    return object_response(data)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require("ProgramAdmin")
    body = body_of(request)
    target = datetime_field(body, "to_iso8601")
    if target < now():
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "The logical clock may not be moved backwards.",
        )
    db.clock = target
    return object_response({"current_utc": fmt_dt(db.clock)})
