"""The case calendar: placing, scoring and continuing hearings (PRD 3.5)."""
from flask import Blueprint, request

import cascades
import derive
import serializers as S
from auth import require
from envelope import array_response, object_response, paginate, read_pagination
from errors import ApiError
from store import db, new_row, now, touch
from util import fmt_dt, parse_dt
from validation import (
    body_of,
    bool_field,
    datetime_field,
    enum_field,
    query_enum,
    query_str,
    str_field,
)

bp = Blueprint("calendar", __name__)

HEARING_TYPES = (
    "ARRAIGNMENT",
    "DETENTION_REVIEW",
    "TRIAL",
    "PLEA",
    "SENTENCING",
    "MOTION",
    "CIVIL_MOTION",
)
DELIVERY_MODES = ("IN_PERSON", "VRI", "TELEPHONIC")
HEARING_STATUSES = ("SCHEDULED", "COVERED", "SERVED", "UNMET", "CONTINUED")
PRIORITY_CLASSES = ("A", "B", "C")
CONTINUANCE_REASONS = ("COURT_CONGESTION", "PARTY_REQUEST", "NO_INTERPRETER_AVAILABLE")
WRITE_ROLES = ("SchedulingCoordinator", "ProgramAdmin")
LIST_ROLES = (
    "ProgramAdmin",
    "SchedulingCoordinator",
    "CredentialingOfficer",
    "QualityReviewer",
    "FiscalOfficer",
)


@bp.route("/hearings", methods=["POST"])
def create_hearing():
    require(*WRITE_ROLES)
    body = body_of(request)
    courthouse_id = str_field(body, "courthouse_id")
    language_id = str_field(body, "language_id")
    case_number = str_field(body, "case_number")
    hearing_type = enum_field(body, "hearing_type", HEARING_TYPES)
    in_custody = bool_field(body, "in_custody")
    scheduled_start = datetime_field(body, "scheduled_start")
    scheduled_end = datetime_field(body, "scheduled_end")
    requested_delivery_mode = enum_field(
        body, "requested_delivery_mode", DELIVERY_MODES
    )
    if scheduled_end <= scheduled_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "scheduled_end must be strictly after scheduled_start.",
        )

    derive.get_courthouse(courthouse_id)
    language = derive.get_language(language_id)

    lead_time_days, priority_score, priority_class = derive.hearing_priority(
        hearing_type, in_custody, language["tier_class"], scheduled_start
    )

    row = new_row()
    row.update(
        {
            "courthouse_id": courthouse_id,
            "language_id": language_id,
            "case_number": case_number,
            "hearing_type": hearing_type,
            "in_custody": in_custody,
            "scheduled_start": fmt_dt(scheduled_start),
            "scheduled_end": fmt_dt(scheduled_end),
            "requested_delivery_mode": requested_delivery_mode,
            "status": "SCHEDULED",
            "lead_time_days": lead_time_days,
            "priority_score": priority_score,
            "priority_class": priority_class,
            "continuance_count": 0,
            "continuance_reason_code": None,
        }
    )
    db.hearings[row["id"]] = row
    return object_response(S.hearing_out(row), 201)


@bp.route("/hearings", methods=["GET"])
def list_hearings():
    require(*LIST_ROLES)
    limit, offset = read_pagination(request.args)
    courthouse_id = query_str(request.args, "courthouse_id")
    language_id = query_str(request.args, "language_id")
    status = query_enum(request.args, "status", HEARING_STATUSES)
    priority_class = query_enum(request.args, "priority_class", PRIORITY_CLASSES)
    rows = []
    for row in db.hearings.values():
        if courthouse_id is not None and row["courthouse_id"] != courthouse_id:
            continue
        if language_id is not None and row["language_id"] != language_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if priority_class is not None and row["priority_class"] != priority_class:
            continue
        rows.append(row)
    rows = sorted(rows, key=lambda r: (r["scheduled_start"], r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return array_response([S.hearing_out(r) for r in page], limit, offset, total)


@bp.route("/hearings/<hearing_id>", methods=["GET"])
def get_hearing(hearing_id):
    require(*LIST_ROLES, "Interpreter")
    row = derive.get_hearing(hearing_id)
    return object_response(S.hearing_out(row))


@bp.route("/hearings/<hearing_id>/continue", methods=["POST"])
def continue_hearing(hearing_id):
    require(*WRITE_ROLES)
    body = body_of(request)
    reason_code = enum_field(body, "reason_code", CONTINUANCE_REASONS)

    hearing = derive.get_hearing(hearing_id)
    if hearing["status"] not in ("SCHEDULED", "COVERED"):
        raise ApiError(
            "ERR_HEARING_NOT_SCHEDULABLE",
            "A served, unmet or already continued hearing cannot be continued.",
        )
    if now() >= parse_dt(hearing["scheduled_start"]):
        raise ApiError(
            "ERR_HEARING_WINDOW_CLOSED",
            "The hearing has already started on the logical clock.",
        )

    hearing["status"] = "CONTINUED"
    hearing["continuance_count"] = hearing["continuance_count"] + 1
    hearing["continuance_reason_code"] = reason_code
    touch(hearing)

    live = [
        a
        for a in derive.assignments_of_hearing(hearing_id)
        if a["service_status"] in derive.CANCELLABLE_SERVICE_STATUSES
    ]
    cascades.cancel_live_assignments(live, "COURT_CONTINUANCE")
    return object_response(S.hearing_out(hearing))


@bp.route("/hearings/<hearing_id>/eligible-interpreters", methods=["GET"])
def list_eligible_interpreters(hearing_id):
    require(*WRITE_ROLES)
    limit, offset = read_pagination(request.args)
    hearing = derive.get_hearing(hearing_id)
    rows = derive.eligible_interpreters(hearing)
    page, total = paginate(rows, limit, offset)
    return array_response([S.interpreter_out(r) for r in page], limit, offset, total)
