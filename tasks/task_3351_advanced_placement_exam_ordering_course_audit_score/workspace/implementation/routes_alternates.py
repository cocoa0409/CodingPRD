"""Alternate-exam requests and the seat-occupancy machine."""

import auth
import calc
import clock
import core
from core import app, body, enum_field, insert, require, str_field
from entities import make, serialize
from errors import fail
from response import ok
from validation import require_fk, transition_gate


@app.route("/ap-program/alternate-exam-requests", methods=["POST"])
def create_alternate_request():
    auth.authenticate(["SchoolCoordinator"])
    payload = body()
    exam_registration_id = str_field(payload, "exam_registration_id")
    alternate_date_utc = str_field(payload, "alternate_date_utc")
    reason_code = enum_field(payload, "reason_code",
                             ["SCHEDULE_CONFLICT", "ILLNESS", "RELIGIOUS_OBSERVANCE",
                              "EMERGENCY", "OTHER"])
    form_code = str_field(payload, "form_code")
    require_fk("exam_registrations", exam_registration_id, "exam_registration_id")
    clock.parse_instant(alternate_date_utc)
    request_row = insert("alternate_exam_requests", make(
        "alternate_exam_requests",
        exam_registration_id=exam_registration_id,
        alternate_date_utc=alternate_date_utc,
        reason_code=reason_code,
        form_code=form_code,
    ))
    return ok(serialize("alternate_exam_requests", request_row), status=201)


@app.route("/ap-program/alternate-exam-requests/<rid>/status-transitions", methods=["POST"])
def transition_alternate_request(rid):
    _role, actor = auth.authenticate(["SchoolCoordinator", "PlatformAdmin"])
    payload = body()
    request_row, to_status = transition_gate(
        "alternate_exam_requests", rid, payload,
        occ_field="expected_alternate_exam_request_version", actor=actor,
    )
    registration = core.require("exam_registrations", request_row["exam_registration_id"])

    if to_status == "UNDER_REVIEW":
        if not (request_row.get("form_code") or "").strip():
            fail("ERR_INVALID_STATE", "The request carries no alternate form code.")
        if registration["status"] != "CONFIRMED":
            fail("ERR_INVALID_STATE", "The linked registration is not confirmed.")
        request_row["status"] = "UNDER_REVIEW"
        core.touch(request_row)

    elif to_status == "APPROVED":
        student = core.get("students", registration["student_id"])
        school = core.get("schools", student["school_id"]) if student else None
        if school is None:
            fail("ERR_INVALID_STATE", "The registration's student has no school of record.")
        if calc.alternate_seat_overflow(school, request_row):
            request_row["seat_block_conflict"] = True
            fail("ERR_ALT_SEAT_CONFLICT")
        request_row["seat_block_conflict"] = False
        request_row["status"] = "APPROVED"
        core.touch(request_row)

    elif to_status == "SCHEDULED":
        if not (request_row.get("form_code") or "").strip():
            fail("ERR_NO_ALTERNATE_FORM")
        if registration["status"] != "CONFIRMED":
            fail("ERR_INVALID_STATE", "The linked registration is not confirmed.")
        request_row["status"] = "SCHEDULED"
        core.touch(request_row)

    elif to_status == "FILED":
        new_date = payload.get("alternate_date_utc")
        if new_date is None or not str(new_date).strip():
            fail("ERR_INVALID_REQUEST", "Field 'alternate_date_utc' is required for a refile.")
        clock.parse_instant(new_date)
        if new_date == request_row["alternate_date_utc"]:
            fail("ERR_INVALID_STATE", "The refiled date must differ from the approved date.")
        request_row["alternate_date_utc"] = new_date
        request_row["seat_block_conflict"] = False
        request_row["status"] = "FILED"
        core.touch(request_row)

    elif to_status == "DENIED":
        student = core.get("students", registration["student_id"])
        school = core.get("schools", student["school_id"]) if student else None
        overflow = bool(school) and calc.alternate_seat_overflow(school, request_row)
        if request_row["reason_code"] != "OTHER" and not overflow:
            fail("ERR_INVALID_STATE", "Denial requires an OTHER reason or a seat overflow.")
        request_row["seat_block_conflict"] = overflow
        request_row["status"] = "DENIED"
        core.touch(request_row)

    elif to_status == "WITHDRAWN":
        request_row["status"] = "WITHDRAWN"
        core.touch(request_row)

    return ok(serialize("alternate_exam_requests", request_row))
