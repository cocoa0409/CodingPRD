from flask import Blueprint

from db import store, new_entity, touch, clock_date_str
from errors import ApiError, bad_request, not_found, invalid_state
from middleware import (auth, body, need, need_str, need_int, need_enum, is_num)
from response import ok
from serialize import student_json
import services as svc

bp = Blueprint("students", __name__)

FOCUS_LIST_TYPES = {"ATTENDANCE", "LITERACY", "MATH"}
CASELOAD_CAP = 12


def get_student_or_404(student_id):
    s = store.students.get(student_id)
    if s is None:
        not_found("Student not found")
    return s


def _validate_pct(v, field):
    if not is_num(v) or v < 0 or v > 100:
        bad_request("%s must be a number between 0 and 100" % field)
    return v


@bp.route("/corps/students", methods=["POST"])
def create_student():
    auth(["ProgramManager"])
    data = body()
    school_id = need_str(data, "school_id")
    ref = need_str(data, "external_student_ref")
    grade = need_int(data, "grade_level")
    if grade < 0 or grade > 12:
        bad_request("grade_level must be between 0 and 12")
    flt = need_enum(data, "focus_list_type", FOCUS_LIST_TYPES)
    baseline = _validate_pct(need(data, "baseline_attendance_pct"),
                             "baseline_attendance_pct")
    school = store.schools.get(school_id)
    if school is None:
        not_found("School not found")
    if school["agreement_status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409,
                       "School agreement is not ACTIVE")
    s = new_entity({
        "school_id": school_id,
        "external_student_ref": ref,
        "grade_level": grade,
        "focus_list_type": flt,
        "baseline_attendance_pct": baseline,
        "current_attendance_pct": None,
        "enrollment_status": "ACTIVE",
        "caseload_status": "UNASSIGNED",
        "assigned_member_id": None,
        "assigned_start_date": None,
        "assigned_end_date": None,
        "_caseload_members": [],
    })
    store.students[s["id"]] = s
    return ok(student_json(s), 201)


@bp.route("/corps/students/<student_id>/state", methods=["POST"])
def student_state(student_id):
    auth(["ProgramManager"])
    data = body()
    to_status = need(data, "to_status")
    if to_status not in ("ACTIVE", "EXITED"):
        bad_request("to_status must be a valid enrollment status")
    s = get_student_or_404(student_id)
    if to_status == "EXITED" and s["enrollment_status"] == "ACTIVE":
        s["enrollment_status"] = "EXITED"
        if s["caseload_status"] == "ASSIGNED":
            s["caseload_status"] = "UNASSIGNED"
            s["assigned_end_date"] = clock_date_str()
            s["assigned_member_id"] = None
    else:
        invalid_state("enrollment_status %s cannot transition to %s"
                      % (s["enrollment_status"], to_status))
    touch(s)
    return ok(student_json(s), 200)


def _member_placed_at_school(member, school_id):
    for a in svc.assignments_of_member(member["id"]):
        if a["status"] != "ACTIVE":
            continue
        team = store.teams.get(a["team_id"])
        if team is None:
            continue
        if team["school_id"] == school_id and team["status"] in ("DEPLOYED", "UNDERSTAFFED"):
            return True
    return False


@bp.route("/corps/students/<student_id>/caseload", methods=["POST"])
def student_caseload(student_id):
    auth(["ProgramManager"])
    data = body()
    action = need(data, "action")
    if action not in ("ASSIGN", "UNASSIGN"):
        bad_request("action must be ASSIGN or UNASSIGN")
    corps_member_id = None
    if action == "ASSIGN":
        corps_member_id = need_str(data, "corps_member_id")
    s = get_student_or_404(student_id)
    if action == "UNASSIGN":
        if s["caseload_status"] != "ASSIGNED":
            invalid_state("Student is not ASSIGNED")
        s["caseload_status"] = "UNASSIGNED"
        s["assigned_end_date"] = clock_date_str()
        s["assigned_member_id"] = None
        touch(s)
        return ok(student_json(s), 200)
    # ASSIGN
    m = store.members.get(corps_member_id)
    if m is None:
        not_found("CorpsMember not found")
    if s["enrollment_status"] != "ACTIVE":
        invalid_state("Student enrollment is not ACTIVE")
    if m["service_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409,
                       "Member service_status is not ACTIVE")
    if not _member_placed_at_school(m, s["school_id"]):
        raise ApiError("ERR_MEMBER_NOT_PLACED", 422,
                       "Member holds no ACTIVE assignment to a "
                       "DEPLOYED/UNDERSTAFFED team at this school")
    if svc.member_active_caseload_count(m) >= CASELOAD_CAP:
        raise ApiError("ERR_CASELOAD_FULL", 422,
                       "Member already holds 12 ASSIGNED students")
    if s["caseload_status"] == "ASSIGNED":
        raise ApiError("ERR_STUDENT_CASELOAD_CONFLICT", 409,
                       "Student is already ASSIGNED")
    s["assigned_member_id"] = m["id"]
    s["assigned_start_date"] = clock_date_str()
    s["assigned_end_date"] = None
    s["caseload_status"] = "ASSIGNED"
    s["_caseload_members"].append(m["id"])
    touch(s)
    return ok(student_json(s), 200)


@bp.route("/corps/students/<student_id>/metrics", methods=["POST"])
def student_metrics(student_id):
    auth(["ProgramManager"])
    data = body()
    pct = _validate_pct(need(data, "current_attendance_pct"),
                        "current_attendance_pct")
    s = get_student_or_404(student_id)
    s["current_attendance_pct"] = pct
    touch(s)
    return ok(student_json(s), 200)
