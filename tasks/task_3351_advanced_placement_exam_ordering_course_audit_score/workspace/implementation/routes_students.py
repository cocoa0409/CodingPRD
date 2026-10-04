"""Students: enrollment, the enrollment dimension and the nested reads."""

from flask import request

import auth
import core
from core import app, body, enum_field, insert, int_field, require, rows, str_field
from entities import make, serialize
from response import list_response, ok
from validation import optional_version, require_fk, require_unique


@app.route("/ap-program/students", methods=["POST"])
def create_student():
    auth.authenticate(["SchoolCoordinator"])
    payload = body()
    full_name = str_field(payload, "full_name")
    school_id = str_field(payload, "school_id")
    student_code = str_field(payload, "student_code")
    grade_level = int_field(payload, "grade_level")
    require_fk("schools", school_id, "school_id")
    require_unique("students", "student_code", student_code,
                   scope=school_id, scope_field="school_id")
    student = insert("students", make(
        "students",
        full_name=full_name,
        school_id=school_id,
        student_code=student_code,
        grade_level=grade_level,
    ))
    return ok(serialize("students", student), status=201)


@app.route("/ap-program/students", methods=["GET"])
def list_students():
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator", "AccommodationReviewer"])
    args = request.args
    school_id = args.get("school_id")
    grade_level = args.get("grade_level")
    student_code = args.get("student_code")
    matching = []
    for student in rows("students"):
        if school_id is not None and student["school_id"] != school_id:
            continue
        if grade_level is not None and str(student["grade_level"]) != str(grade_level):
            continue
        if student_code is not None and student["student_code"] != student_code:
            continue
        matching.append(student)
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, args, lambda r: serialize("students", r))


@app.route("/ap-program/students/<rid>", methods=["GET"])
def read_student(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator", "AccommodationReviewer", "SchoolStudent"])
    return ok(serialize("students", require("students", rid)))


@app.route("/ap-program/students/<rid>/status-transitions", methods=["POST"])
def transition_student(rid):
    auth.authenticate(["SchoolCoordinator"])
    payload = body()
    student = require("students", rid)
    to_status = enum_field(payload, "to_status", ["ACTIVE", "INACTIVE"])
    optional_version(payload, "expected_student_version", student)
    student["enrolled"] = to_status == "ACTIVE"
    core.touch(student)
    return ok(serialize("students", student))


@app.route("/ap-program/students/<rid>/registrations", methods=["GET"])
def list_student_registrations(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator", "SchoolStudent"])
    require("students", rid)
    matching = [r for r in rows("exam_registrations") if r["student_id"] == rid]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, request.args, lambda r: serialize("exam_registrations", r))


@app.route("/ap-program/students/<rid>/accommodation-requests", methods=["GET"])
def list_student_accommodations(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator", "AccommodationReviewer"])
    require("students", rid)
    matching = [a for a in rows("accommodation_requests") if a["student_id"] == rid]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, request.args, lambda r: serialize("accommodation_requests", r))
