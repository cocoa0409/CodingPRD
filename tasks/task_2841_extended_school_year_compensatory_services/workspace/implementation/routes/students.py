"""Student registration and the running minute ledger (PRD section 3.1)."""
from flask import Blueprint

from auth import (CASE_MANAGER, COMPLIANCE_OFFICER, PARENT_GUARDIAN,
                  PROGRAM_COORDINATOR, SPED_DIRECTOR, endpoint,
                  guard_student_scope)
from envelope import created, ok, ok_list, paginate
from resolve import path_ref
from serialize import many, public
from store import creation_order, db, new_record
from validate import bad, body, req_bool, req_enum, req_int, req_str

bp = Blueprint("students", __name__)

GRADE_BANDS = ("PRE_K", "K_5", "MS_6_8", "HS_9_12")
PRIMARY_DISABILITIES = (
    "AUTISM", "INTELLECTUAL_DISABILITY", "SPECIFIC_LEARNING_DISABILITY",
    "SPEECH_LANGUAGE_IMPAIRMENT", "EMOTIONAL_DISTURBANCE", "MULTIPLE_DISABILITIES",
)
READ_ROLES = (CASE_MANAGER, PROGRAM_COORDINATOR, SPED_DIRECTOR,
              COMPLIANCE_OFFICER, PARENT_GUARDIAN)
DUE_PROCESS_READ_ROLES = (CASE_MANAGER, SPED_DIRECTOR, COMPLIANCE_OFFICER)


@bp.post("/esy/students")
@endpoint((CASE_MANAGER,))
def create_student():
    data = body()
    student_number = req_str(data, "student_number", 1, 16)
    first_name = req_str(data, "first_name", 1, 40)
    last_name = req_str(data, "last_name", 1, 40)
    grade_band = req_enum(data, "grade_band", GRADE_BANDS)
    primary_disability = req_enum(data, "primary_disability", PRIMARY_DISABILITIES)
    iep_weekly_minutes_total = req_int(data, "iep_weekly_minutes_total", 1, 3000)
    home_school_code = req_str(data, "home_school_code", 1, 12)
    transportation_required = req_bool(data, "transportation_required", False)

    if any(s["student_number"] == student_number for s in db.students.values()):
        raise bad("student_number must be unique across all students.")

    student = new_record("Student", {
        "student_number": student_number,
        "first_name": first_name,
        "last_name": last_name,
        "grade_band": grade_band,
        "primary_disability": primary_disability,
        "iep_weekly_minutes_total": iep_weekly_minutes_total,
        "transportation_required": transportation_required,
        "home_school_code": home_school_code,
        "esy_eligibility_status": "NOT_DETERMINED",
        "pending_award_minutes": 0,
        "outstanding_owed_minutes": 0,
        "delivered_makeup_minutes_total": 0,
        "esy_service_alert": False,
        "stay_put_active": False,
    })
    db.students[student["id"]] = student
    return created(public(student))


@bp.get("/esy/students/<student_id>")
@endpoint(READ_ROLES)
def get_student(student_id):
    # PRD 2.7: the guardian ownership check (3) precedes path resolution (5),
    # and for this read the addressed Student's own id is the compared value.
    guard_student_scope(student_id)
    return ok(public(path_ref("student", student_id)))


@bp.get("/esy/students/<student_id>/eligibility-determinations")
@endpoint(READ_ROLES)
def list_student_determinations(student_id):
    guard_student_scope(student_id)
    path_ref("student", student_id)
    rows = creation_order([d for d in db.determinations.values()
                           if d["student_id"] == student_id])
    page, page_meta = paginate(rows)
    return ok_list(many(page), page_meta)


@bp.get("/esy/students/<student_id>/due-process-records")
@endpoint(DUE_PROCESS_READ_ROLES)
def list_student_due_process_records(student_id):
    path_ref("student", student_id)
    rows = creation_order([r for r in db.records.values()
                           if r["student_id"] == student_id])
    page, page_meta = paginate(rows)
    return ok_list(many(page), page_meta)
