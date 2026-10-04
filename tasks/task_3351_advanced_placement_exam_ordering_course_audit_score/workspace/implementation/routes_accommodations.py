"""Accommodation requests and the documentation-review machine."""

import auth
import calc
import cascades
import core
from constants import DOC_COMPLETENESS_THRESHOLD, MAX_DOC_REVIEW_ROUNDS
from core import app, body, enum_field, insert, int_field, require, rows, str_field
from entities import make, serialize
from errors import fail
from response import ok
from validation import optional_version, require_fk, transition_gate

PRE_SCORED = ("REGISTERED", "FEE_PENDING", "CONFIRMED", "MATERIAL_ASSIGNED")


def _effective_completeness(request_row, payload):
    value = payload.get("documentation_completeness")
    if value is None:
        return request_row["documentation_completeness"]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "documentation_completeness must be an integer.")
    if value < 0 or value > DOC_COMPLETENESS_THRESHOLD:
        fail("ERR_INVALID_REQUEST", "documentation_completeness must be between 0 and 3.")
    return value


def _refresh_provisioning(request_row):
    request_row["weight_sum"] = calc.accommodation_weight_sum(
        request_row["documentation_completeness"],
        request_row["accommodation_type"],
        request_row["review_round"],
    )
    request_row["provisioned_minutes"] = calc.accommodation_provisioned_minutes(
        request_row["accommodation_type"])


@app.route("/ap-program/accommodation-requests", methods=["POST"])
def create_accommodation_request():
    auth.authenticate(["SchoolCoordinator"])
    payload = body()
    student_id = str_field(payload, "student_id")
    exam_subject = str_field(payload, "exam_subject")
    accommodation_type = enum_field(payload, "accommodation_type",
                                    ["EXTENDED_TIME", "ALTERNATE_FORMAT", "SMALL_GROUP", "BREAK_AS_NEEDED"])
    completeness = int_field(payload, "documentation_completeness",
                             minimum=0, maximum=DOC_COMPLETENESS_THRESHOLD)
    submitted_by = str_field(payload, "submitted_by_user_id")
    require_fk("students", student_id, "student_id")
    request_row = insert("accommodation_requests", make(
        "accommodation_requests",
        student_id=student_id,
        exam_subject=exam_subject,
        accommodation_type=accommodation_type,
        documentation_completeness=completeness,
        submitted_by_user_id=submitted_by,
    ))
    request_row["_last_submitted_completeness"] = completeness
    _refresh_provisioning(request_row)
    return ok(serialize("accommodation_requests", request_row), status=201)


@app.route("/ap-program/accommodation-requests/<rid>", methods=["GET"])
def read_accommodation_request(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator", "AccommodationReviewer"])
    return ok(serialize("accommodation_requests", require("accommodation_requests", rid)))


@app.route("/ap-program/accommodation-requests/<rid>/status-transitions", methods=["POST"])
def transition_accommodation_request(rid):
    _role, actor = auth.authenticate(["AccommodationReviewer", "SchoolCoordinator"])
    payload = body()
    request_row, to_status = transition_gate("accommodation_requests", rid, payload, actor=actor)
    optional_version(payload, "expected_accommodation_request_version", request_row)
    completeness = _effective_completeness(request_row, payload)
    student = core.require("students", request_row["student_id"])

    if to_status == "UNDER_DOC_REVIEW":
        if completeness < 1:
            fail("ERR_INVALID_STATE", "At least one documentation item is required.")
        request_row["documentation_completeness"] = completeness
        request_row["review_round"] = request_row["review_round"] + 1
        request_row["status"] = "UNDER_DOC_REVIEW"
        core.touch(request_row)

    elif to_status == "INFO_REQUESTED":
        if completeness >= DOC_COMPLETENESS_THRESHOLD:
            fail("ERR_INVALID_STATE", "The documentation is already complete.")
        request_row["documentation_completeness"] = completeness
        request_row["status"] = "INFO_REQUESTED"
        core.touch(request_row)

    elif to_status == "SUBMITTED":
        if request_row["review_round"] >= MAX_DOC_REVIEW_ROUNDS:
            fail("ERR_INVALID_STATE", "The request has exhausted its documentation review cycles.")
        previous = request_row.get("_last_submitted_completeness")
        if previous is not None and completeness <= previous:
            fail("ERR_INVALID_STATE", "The revised documentation must add new items.")
        request_row["documentation_completeness"] = completeness
        request_row["_last_submitted_completeness"] = completeness
        request_row["status"] = "SUBMITTED"
        core.touch(request_row)

    elif to_status == "APPROVED":
        if completeness < DOC_COMPLETENESS_THRESHOLD:
            fail("ERR_DOCUMENTS_INCOMPLETE")
        request_row["documentation_completeness"] = completeness
        request_row["extended_time_multiplier"] = \
            1.5 if request_row["accommodation_type"] == "EXTENDED_TIME" else 1.0
        request_row["status"] = "APPROVED"
        core.touch(request_row)
        student["accommodation_eligible"] = True
        core.touch(student)
        for reg in cascades.regs_of_student(student["id"]):
            if reg["exam_subject"] != request_row["exam_subject"]:
                continue
            if reg["status"] != "REGISTERED":
                continue
            reg["status"] = "CONFIRMED"
            reg["accommodation_flag"] = True
            core.touch(reg)

    elif to_status == "DENIED":
        if request_row["review_round"] < 1:
            fail("ERR_INVALID_STATE", "Denial requires a completed review round.")
        request_row["extended_time_multiplier"] = 1.0
        request_row["status"] = "DENIED"
        core.touch(request_row)
        cascades.refresh_student_flag(student)
        core.touch(student)

    elif to_status == "REVOKED":
        request_row["status"] = "REVOKED"
        core.touch(request_row)
        cascades.refresh_student_flag(student)
        core.touch(student)
        for reg in cascades.regs_of_student(student["id"]):
            if reg.get("accommodation_flag") and reg["status"] in PRE_SCORED:
                reg["accommodation_flag"] = False

    _refresh_provisioning(request_row)
    return ok(serialize("accommodation_requests", request_row))
