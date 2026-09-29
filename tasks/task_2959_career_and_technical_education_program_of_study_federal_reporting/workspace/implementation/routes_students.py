"""Student, credit-posting and credential-attainment routes (PRD sec 3.6)."""
from flask import Blueprint

import calc
import resolve
import serialize
import services
import shape
from auth import endpoint
from envelope import created, listing, ok, page
from errors import ApiError
from store import (CONCENTRATOR_STATUSES, EXIT_REASONS, SPECIAL_POPULATION_CODES,
                   VERIFICATION_STATUSES, db, dec, fmt_date, next_seq, new_id,
                   stamp_new, touch, wall_stamp)

bp = Blueprint("students", __name__)
REGISTRAR = ("SchoolRegistrar",)
REGISTRAR_DIRECTOR = ("SchoolRegistrar", "CteDirector")
READERS = ("CteDirector", "StateComplianceReviewer", "SchoolRegistrar")


def _block_if_suspended(student):
    program = db.programs.get(student["pos_id"])
    if program is not None and program["approval_status"] == "SUSPENDED":
        raise ApiError("ERR_CREDIT_POSTING_BLOCKED",
                       "Registrar writes are blocked while the program of study "
                       "is SUSPENDED.")


# ------------------------------------------------------------------ reads
@bp.get("/cte/students/<student_id>")
@endpoint(READERS)
def get_student(student_id):
    return ok(serialize.student(resolve.student(student_id)))


@bp.get("/cte/credential-attainments")
@endpoint(READERS)
def list_attainments():
    limit, offset = shape.pagination()
    student_id = shape.filter_str("student_id")
    credential_id = shape.filter_str("credential_id")
    verification = shape.filter_enum("verification_status", VERIFICATION_STATUSES)
    rows = list(db.attainments.values())
    if student_id is not None:
        rows = [r for r in rows if r["student_id"] == student_id]
    if credential_id is not None:
        rows = [r for r in rows if r["credential_id"] == credential_id]
    if verification is not None:
        rows = [r for r in rows if r["verification_status"] == verification]
    rows.sort(key=lambda r: r["_seq"])
    window, total = page(rows, limit, offset)
    return listing([serialize.attainment(r) for r in window], limit, offset, total)


@bp.get("/cte/credential-attainments/<attainment_id>")
@endpoint(READERS)
def get_attainment(attainment_id):
    return ok(serialize.attainment(resolve.attainment(attainment_id)))


# ------------------------------------------------------------------ writes
@bp.post("/cte/programs-of-study/<pos_id>/students")
@endpoint(REGISTRAR)
def enroll_student(pos_id):
    data = shape.body()
    state_student_id = shape.req_string(data, "state_student_id", min_len=9,
                                        max_len=9, pattern=r"\d{9}")
    cohort_year = shape.req_int(data, "cohort_year", minimum=2020, maximum=2035)
    codes = shape.opt_str_list(data, "special_population_codes",
                               allowed=SPECIAL_POPULATION_CODES, unique=True,
                               default=[])
    program = resolve.program(pos_id)
    services.refresh_clna(program)
    for existing in db.students.values():
        if existing["pos_id"] == pos_id \
                and existing["state_student_id"] == state_student_id:
            raise ApiError("ERR_STUDENT_ID_DUPLICATE",
                           "state_student_id '%s' is already enrolled in this "
                           "program." % state_student_id)
    student = stamp_new({
        "pos_id": pos_id,
        "state_student_id": state_student_id,
        "cohort_year": cohort_year,
        "special_population_codes": list(codes),
        "cte_credits_earned": dec("0.00"),
        "concentrator_status": "PARTICIPANT",
        "verified_qualifying_attainment_count": 0,
        "exited_on": None,
        "exit_reason": None,
    })
    db.students[student["id"]] = student
    return created(serialize.student(student))


@bp.post("/cte/students/<student_id>/credit-postings")
@endpoint(REGISTRAR)
def post_credits(student_id):
    data = shape.body()
    course_id = shape.req_string(data, "sequence_course_id")
    credit_delta = shape.req_num(data, "credit_delta", places=2)
    posted_on = shape.req_date(data, "posted_on")
    student = resolve.student(student_id)
    course = resolve.course(course_id)
    _block_if_suspended(student)
    if course["pos_id"] != student["pos_id"] or course["status"] != "ACTIVE":
        raise ApiError("ERR_COURSE_NOT_ACTIVE",
                       "The target course must belong to the student's program "
                       "and be in status ACTIVE.")
    projected = calc.student_credits(student_id) + credit_delta
    if projected < 0:
        raise ApiError("ERR_CREDIT_BALANCE_NEGATIVE",
                       "This posting would drive cte_credits_earned below zero.")
    posting = {
        "id": new_id(),
        "_seq": next_seq(),
        "created_at": wall_stamp(),
        "student_id": student_id,
        "sequence_course_id": course_id,
        "credit_delta": credit_delta,
        "posted_on": fmt_date(posted_on),
    }
    db.postings[posting["id"]] = posting
    calc.classify_student(student)
    touch(student)
    return ok(serialize.student(student))


@bp.post("/cte/students/<student_id>/exit")
@endpoint(REGISTRAR)
def exit_student(student_id):
    data = shape.body()
    exited_on = shape.req_date(data, "exited_on")
    exit_reason = shape.req_enum(data, "exit_reason", EXIT_REASONS)
    student = resolve.student(student_id)
    _block_if_suspended(student)
    student["exited_on"] = fmt_date(exited_on)
    student["exit_reason"] = exit_reason
    calc.classify_student(student)
    touch(student)
    return ok(serialize.student(student))


@bp.post("/cte/students/<student_id>/credential-attainments")
@endpoint(REGISTRAR_DIRECTOR)
def file_attainment(student_id):
    data = shape.body()
    credential_id = shape.req_string(data, "credential_id")
    attained_on = shape.req_date(data, "attained_on")
    verification_status = shape.req_enum(data, "verification_status",
                                         VERIFICATION_STATUSES)
    exam_score = shape.opt_num(data, "exam_score", minimum=0, maximum=100, places=2)
    student = resolve.student(student_id)
    credential = resolve.credential(credential_id)

    if credential["pos_id"] != student["pos_id"]:
        raise ApiError("ERR_CREDENTIAL_PROGRAM_MISMATCH",
                       "The credential belongs to a different program of study.")
    if credential["exam_required"] and exam_score is None:
        raise ApiError("ERR_EXAM_SCORE_REQUIRED",
                       "This credential requires an exam_score.")
    for existing in db.attainments.values():
        if existing["student_id"] == student_id \
                and existing["credential_id"] == credential_id:
            raise ApiError("ERR_DUPLICATE_ATTAINMENT",
                           "An attainment already exists for this student and "
                           "credential.")

    counted = (verification_status == "VERIFIED"
               and bool(credential["counts_toward_indicator"]))
    attainment = stamp_new({
        "student_id": student_id,
        "credential_id": credential_id,
        "attained_on": fmt_date(attained_on),
        "exam_score": exam_score,
        "verification_status": verification_status,
        "counted_for_indicator": counted,
    }, with_version=False)
    db.attainments[attainment["id"]] = attainment
    calc.classify_student(student)
    return created(serialize.attainment(attainment))
