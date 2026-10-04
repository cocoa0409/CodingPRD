"""School registration, the test-center dimension and its nested reads."""

from flask import request

import auth
import core
from core import app, body, bool_field, insert, int_field, require, rows, str_field
from entities import make, serialize
from errors import fail
from response import list_response, ok
from validation import optional_version, require_unique, transition_gate


def _ordered(matching):
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return matching


@app.route("/ap-program/schools", methods=["POST"])
def create_school():
    auth.authenticate(["PlatformAdmin"])
    payload = body()
    name = str_field(payload, "name")
    school_code = str_field(payload, "school_code")
    country_code = str_field(payload, "country_code")
    center_code = str_field(payload, "center_code")
    seat_capacity = int_field(payload, "seat_capacity", minimum=1)
    seal_required = bool_field(payload, "seal_required", True)
    require_unique("schools", "school_code", school_code)
    require_unique("schools", "center_code", center_code)
    school = insert("schools", make(
        "schools",
        name=name,
        school_code=school_code,
        country_code=country_code,
        center_code=center_code,
        seat_capacity=seat_capacity,
        seal_required=seal_required,
    ))
    return ok(serialize("schools", school), status=201)


@app.route("/ap-program/schools/<rid>", methods=["GET"])
def read_school(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator", "IntegrityInvestigator"])
    return ok(serialize("schools", require("schools", rid)))


@app.route("/ap-program/schools/<rid>/status-transitions", methods=["POST"])
def transition_school(rid):
    _role, actor = auth.authenticate(["PlatformAdmin"])
    payload = body()
    school, to_status = transition_gate("schools", rid, payload, actor=actor)
    optional_version(payload, "expected_school_version", school)
    if to_status == "SUSPENDED":
        confirmed = any(
            case["test_center_id"] == school["id"]
            and case["status"] == "CONFIRMED"
            and case["irregularity_type"] == "ADMINISTRATOR_MISCONDUCT"
            for case in rows("irregularity_cases")
        )
        if not confirmed:
            fail("ERR_INVALID_STATE",
                 "Suspension requires a confirmed administrator-misconduct case.")
    elif to_status == "ACTIVE":
        for case in rows("irregularity_cases"):
            if case["test_center_id"] == school["id"] and case["status"] != "DISMISSED":
                fail("ERR_INVALID_STATE", "Not every hosted irregularity case is dismissed.")
    elif to_status == "RETIRED":
        student_ids = {s["id"] for s in rows("students") if s["school_id"] == school["id"]}
        for req in rows("alternate_exam_requests"):
            reg = core.get("exam_registrations", req["exam_registration_id"])
            if reg is None or reg["student_id"] not in student_ids:
                continue
            if req["status"] not in ("DENIED", "WITHDRAWN"):
                fail("ERR_INVALID_STATE", "Not every alternate request is closed.")
    school["test_center_status"] = to_status
    core.touch(school)
    return ok(serialize("schools", school))


@app.route("/ap-program/schools/<rid>/course-audits", methods=["GET"])
def list_school_audits(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator", "CourseAuditReviewer"])
    require("schools", rid)
    matching = _ordered([a for a in rows("course_audits") if a["school_id"] == rid])
    return list_response(matching, request.args, lambda r: serialize("course_audits", r))


@app.route("/ap-program/schools/<rid>/irregularity-cases", methods=["GET"])
def list_school_cases(rid):
    auth.authenticate(["PlatformAdmin", "IntegrityInvestigator"])
    require("schools", rid)
    matching = _ordered([c for c in rows("irregularity_cases") if c["test_center_id"] == rid])
    return list_response(matching, request.args, lambda r: serialize("irregularity_cases", r))
