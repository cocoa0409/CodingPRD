"""Student-athletes, major declaration, the summary, enrollments (PRD 3.2)."""


from flask import Blueprint, request

import calc
import derive
import envelope
import helpers as h
import store as st
from errors import ApiError
from store import D, q1, q2, q4
from validation import (authenticate, bad_request, json_body, want_action,
                        want_decimal, want_enum, want_int, want_string, forbid)

bp = Blueprint("students", __name__)

STUDENT_READ_ONE = ["Registrar", "AcademicAdvisor", "CertificationOfficer",
                    "LearningSpecialist", "ComplianceOfficer", "AppealsCommittee",
                    "AthleticsOperations", "StudentAthlete"]
STUDENT_LIST = ["Registrar", "AcademicAdvisor", "CertificationOfficer",
                "LearningSpecialist", "ComplianceOfficer", "AppealsCommittee",
                "AthleticsOperations"]
SUMMARY_READ = ["Registrar", "AcademicAdvisor", "CertificationOfficer",
                "LearningSpecialist", "ComplianceOfficer", "AppealsCommittee",
                "StudentAthlete"]
ENROLLMENT_READ = ["Registrar", "AcademicAdvisor", "CertificationOfficer",
                   "LearningSpecialist", "ComplianceOfficer", "Instructor", "Tutor"]

ENROLLMENT_STATUSES = ("ENROLLED", "COMPLETED", "DROPPED", "WITHDRAWN", "INCOMPLETE")
NON_TERMINAL_ENROLLMENT = ("ENROLLED", "INCOMPLETE")


# ------------------------------------------------------- student-athletes
@bp.get("/athletics/student-athletes/<student_athlete_id>")
def get_student(student_athlete_id):
    user_id, role = authenticate(STUDENT_READ_ONE)
    if role == "StudentAthlete" and user_id != student_athlete_id:
        raise ApiError("ERR_NOT_OWN_RECORD")
    return h.ok(h.student_or_404(student_athlete_id))


@bp.get("/athletics/student-athletes")
def list_students():
    authenticate(STUDENT_LIST)
    return h.listing(
        h.sorted_students(),
        ("declared_program_id", "sport_code", "risk_tier", "eligibility_state",
         "support_status"),
    )


@bp.post("/athletics/student-athletes")
def create_student():
    authenticate(["Registrar"])
    body = json_body()
    full_name = want_string(body, "full_name")
    sport_code = want_enum(body, "sport_code", calc.SPORT_CODES)
    entry_term_index = want_int(body, "entry_term_index", minimum=1)
    entry_catalog_year = want_int(body, "entry_catalog_year")
    transfer_status = want_enum(body, "transfer_status",
                                ("NATIVE", "INCOMING_TRANSFER"),
                                required=False, default="NATIVE")
    allowance = want_decimal(body, "missed_class_units_allowance", required=False,
                             default=calc.DEFAULT_MISSED_CLASS_ALLOWANCE, minimum=0)
    allowance = q2(allowance)

    student = {
        "full_name": full_name,
        "sport_code": sport_code,
        "entry_term_index": entry_term_index,
        "entry_catalog_year": entry_catalog_year,
        "transfer_status": transfer_status,
        "declared_program_id": None,
        "major_declared_term_index": None,
        "eligibility_state": "NOT_CERTIFIED",
        "support_status": "SUPPORT_NORMAL",
        "cumulative_gpa": q2("0"),
        "completed_full_time_terms": 0,
        "degree_applicable_credits": q2("0"),
        "progress_pct": q4("0"),
        "transfer_credits_accepted": q2("0"),
        "risk_score": q2("0"),
        "risk_tier": "TIER_1",
        "required_study_hall_hours": q1("0"),
        "missed_class_units_allowance": allowance,
        "missed_class_units_charged": q2("0"),
        "missed_class_units_remaining": allowance,
        "apr_points_possible": 0,
        "apr_points_earned": 0,
        "apr_points_forfeited": 0,
        "substantiated_penalty_points": 0,
    }
    st.stamp_new(student)
    st.students[student["id"]] = student
    return h.created(student)


@bp.post("/athletics/student-athletes/<student_athlete_id>/major-declaration")
def declare_major(student_athlete_id):
    authenticate(["Registrar", "AcademicAdvisor"])
    student = h.student_or_404(student_athlete_id)
    body = json_body()
    program = h.body_fk(body, "declared_program_id", h.program_or_404)
    term = h.body_fk(body, "term_id", h.term_or_404)
    program_id = want_string(body, "declared_program_id")
    term_id = want_string(body, "term_id")
    if program is None:
        program = h.program_or_404(program_id)
    if term is None:
        term = h.term_or_404(term_id)

    limit = (student["entry_term_index"]
             + program["major_declaration_deadline_term_count"] - 1)
    if term["term_index"] > limit:
        raise ApiError("ERR_MAJOR_DECLARATION_DEADLINE_PASSED")

    student["declared_program_id"] = program["id"]
    student["major_declared_term_index"] = term["term_index"]
    derive.recompute_student(student)
    derive.derive_eligibility_state(student)
    st.touch(student)
    return h.ok(student)


@bp.get("/athletics/student-athletes/<student_athlete_id>/eligibility-summary")
def eligibility_summary(student_athlete_id):
    user_id, role = authenticate(SUMMARY_READ)
    if role == "StudentAthlete" and user_id != student_athlete_id:
        raise ApiError("ERR_NOT_OWN_RECORD")
    student = h.student_or_404(student_athlete_id)

    audit_variant = request.args.get("audit_variant")
    risk_variant = request.args.get("risk_variant")
    if audit_variant is not None and audit_variant not in calc.AUDIT_VARIANTS:
        raise bad_request("Query parameter 'audit_variant' is not a declared variant.")
    if risk_variant is not None and risk_variant not in calc.RISK_VARIANTS:
        raise bad_request("Query parameter 'risk_variant' is not a declared variant.")

    picture = derive.compute_picture(student, audit_variant=audit_variant,
                                    risk_variant=risk_variant)
    if audit_variant is None and risk_variant is None:
        derive.persist_picture(student, picture)

    data = {
        "student_athlete_id": student["id"],
        "audit_variant": picture["audit_variant"],
        "risk_variant": picture["risk_variant"],
        "degree_applicable_credits": picture["degree_applicable_credits"],
        "progress_pct": picture["progress_pct"],
        "required_progress_pct": picture["required_progress_pct"],
        "benchmark_result": picture["benchmark_result"],
        "failure_reasons": picture["failure_reasons"],
        "cumulative_gpa": picture["cumulative_gpa"],
        "completed_full_time_terms": picture["completed_full_time_terms"],
        "transfer_credits_accepted": picture["transfer_credits_accepted"],
        "risk_score": picture["risk_score"],
        "risk_tier": picture["risk_tier"],
        "required_study_hall_hours": picture["required_study_hall_hours"],
        "missed_class_units_charged": student["missed_class_units_charged"],
        "missed_class_units_remaining": student["missed_class_units_remaining"],
        "apr_points_possible": student["apr_points_possible"],
        "apr_points_earned": student["apr_points_earned"],
        "apr_points_forfeited": student["apr_points_forfeited"],
        "version": student["version"],
    }
    return envelope.object_response(data, 200)


# ------------------------------------------------------------- enrollments
@bp.get("/athletics/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    authenticate(ENROLLMENT_READ)
    return h.ok(h.enrollment_or_404(enrollment_id))


@bp.get("/athletics/enrollments")
def list_enrollments():
    authenticate(ENROLLMENT_READ)
    return h.listing(
        st.by_created(list(st.enrollments.values())),
        ("student_athlete_id", "course_id", "term_id", "status", "credit_source"),
    )


@bp.post("/athletics/enrollments")
def create_enrollment():
    authenticate(["Registrar"])
    body = json_body()
    student = h.body_fk(body, "student_athlete_id", h.student_or_404)
    course = h.body_fk(body, "course_id", h.course_or_404)
    term = h.body_fk(body, "term_id", h.term_or_404)
    student_id = want_string(body, "student_athlete_id")
    course_id = want_string(body, "course_id")
    term_id = want_string(body, "term_id")
    if student is None:
        student = h.student_or_404(student_id)
    if course is None:
        course = h.course_or_404(course_id)
    if term is None:
        term = h.term_or_404(term_id)
    credit_hours = want_decimal(body, "credit_hours", required=False, default=None,
                                maximum=12)
    if credit_hours is not None and credit_hours <= 0:
        raise bad_request("Field 'credit_hours' must be greater than zero.")
    credit_source = want_enum(body, "credit_source", ("RESIDENT", "TRANSFER"),
                              required=False, default="RESIDENT")
    if credit_hours is None:
        credit_hours = D(course["credit_hours"])

    for existing in st.enrollments.values():
        if (existing["student_athlete_id"] == student["id"]
                and existing["course_id"] == course["id"]
                and existing["term_id"] == term["id"]
                and existing["status"] in NON_TERMINAL_ENROLLMENT):
            raise ApiError("ERR_DUPLICATE_ENROLLMENT")

    enrollment = {
        "student_athlete_id": student["id"],
        "course_id": course["id"],
        "term_id": term["id"],
        "credit_hours": q2(credit_hours),
        "credit_source": credit_source,
        "status": "COMPLETED" if credit_source == "TRANSFER" else "ENROLLED",
        "grade": None,
        "grade_points": None,
        "earned_credit_hours": (q2(credit_hours) if credit_source == "TRANSFER"
                                else q2("0")),
        "degree_applicable_credits_counted": q2("0"),
        "is_full_time_countable": False,
        "outcome_recorded_at": None,
    }
    st.stamp_new(enrollment)
    st.enrollments[enrollment["id"]] = enrollment
    return h.created(enrollment)


@bp.post("/athletics/enrollments/<enrollment_id>/outcome")
def record_outcome(enrollment_id):
    authenticate(["Registrar"])
    enrollment = h.enrollment_or_404(enrollment_id)
    body = json_body()
    action = want_action(body, ("RECORD_GRADE", "MARK_INCOMPLETE", "DROP", "WITHDRAW"))
    if action == "RECORD_GRADE":
        grade = want_enum(body, "grade", calc.GRADES, required=True)
    else:
        forbid(body, "grade", action)
        grade = None

    term = st.terms.get(enrollment["term_id"])
    h.require_term_open(term)

    status = enrollment["status"]
    if action == "RECORD_GRADE":
        if status not in ("ENROLLED", "INCOMPLETE"):
            raise h.invalid_transition()
    elif action == "MARK_INCOMPLETE":
        if status != "ENROLLED":
            raise h.invalid_transition()
    elif action == "DROP":
        if status != "ENROLLED":
            raise h.invalid_transition()
    else:
        if status not in ("ENROLLED", "INCOMPLETE"):
            raise h.invalid_transition()

    student = st.students[enrollment["student_athlete_id"]]

    if action == "RECORD_GRADE":
        enrollment["status"] = "COMPLETED"
        enrollment["grade"] = grade
        enrollment["grade_points"] = q2(calc.GRADE_POINTS[grade])
        enrollment["earned_credit_hours"] = (
            q2(enrollment["credit_hours"]) if calc.GRADE_POINTS[grade] > 0 else q2("0")
        )
    elif action == "MARK_INCOMPLETE":
        enrollment["status"] = "INCOMPLETE"
        enrollment["earned_credit_hours"] = q2("0")
    elif action == "DROP":
        enrollment["status"] = "DROPPED"
        enrollment["earned_credit_hours"] = q2("0")
        enrollment["degree_applicable_credits_counted"] = q2("0")
    else:
        enrollment["status"] = "WITHDRAWN"
        enrollment["earned_credit_hours"] = q2("0")
    enrollment["outcome_recorded_at"] = st.now_iso()
    st.touch(enrollment)

    derive.recompute_student(student)
    if action == "DROP":
        enrollment["degree_applicable_credits_counted"] = q2("0")

    if action in ("DROP", "WITHDRAW"):
        _terminate_assignments_of_enrollment(enrollment)
        derive.recompute_support_only(student)

    st.touch(student)
    return h.ok(enrollment)


def _terminate_assignments_of_enrollment(enrollment):
    """PRD 3.2: DROP and WITHDRAW terminate the enrollment's tutoring."""
    rows = [a for a in st.assignments.values()
            if a["enrollment_id"] == enrollment["id"]]
    for assignment in st.by_created(rows):
        if assignment["status"] not in ("PROPOSED", "ACTIVE"):
            continue
        assignment["status"] = "TERMINATED"
        assignment["terminated_reason"] = "ENROLLMENT_DROPPED"
        st.touch(assignment)
        tutor = st.tutors.get(assignment["tutor_id"])
        if tutor is not None:
            derive.refresh_tutor_capacity(tutor)
            st.touch(tutor)
