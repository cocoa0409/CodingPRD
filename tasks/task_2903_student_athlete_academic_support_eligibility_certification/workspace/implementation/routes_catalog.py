"""Terms, degree programs, courses and degree-applicability rules (PRD 3.1)."""

import re
from decimal import Decimal

from flask import Blueprint

import calc
import derive
import helpers as h
import store as st
from errors import ApiError
from store import q2
from validation import (authenticate, bad_request, json_body, want_bool,
                        want_decimal, want_enum, want_instant, want_int,
                        want_int_list, want_string)

bp = Blueprint("catalog", __name__)

TERM_READ = ["Registrar", "AcademicAdvisor", "CertificationOfficer",
             "LearningSpecialist", "ComplianceOfficer", "AthleticsOperations",
             "AppealsCommittee"]
PROGRAM_READ = ["Registrar", "AcademicAdvisor", "CertificationOfficer",
                "LearningSpecialist", "ComplianceOfficer", "AppealsCommittee"]
COURSE_READ = ["Registrar", "AcademicAdvisor", "CertificationOfficer",
               "LearningSpecialist", "ComplianceOfficer", "Instructor",
               "AthleticsOperations"]
RULE_READ = ["Registrar", "AcademicAdvisor", "CertificationOfficer",
             "ComplianceOfficer", "AppealsCommittee"]

TERM_CODE_RE = re.compile(r"^[0-9]{4}(FA|SP|SU)$")


# ------------------------------------------------------------------- terms
@bp.get("/athletics/terms/<term_id>")
def get_term(term_id):
    authenticate(TERM_READ)
    return h.ok(h.term_or_404(term_id))


@bp.get("/athletics/terms")
def list_terms():
    authenticate(TERM_READ)
    return h.listing(h.sorted_terms(), ("term_type", "apr_status"))


@bp.post("/athletics/terms")
def create_term():
    authenticate(["Registrar"])
    body = json_body()
    code = want_string(body, "code")
    if not TERM_CODE_RE.match(code):
        raise bad_request("Field 'code' must be four digits followed by FA, SP or SU.")
    term_index = want_int(body, "term_index", minimum=1)
    term_type = want_enum(body, "term_type", calc.TERM_TYPES)
    catalog_year = want_int(body, "catalog_year", minimum=2000)
    start_date = want_instant(body, "start_date")
    end_date = want_instant(body, "end_date")
    full_time_minimum = want_int(body, "full_time_credit_minimum", required=False,
                                 default=12, minimum=1)
    is_reporting = want_bool(body, "is_apr_reporting_term", default=True)
    for existing in st.terms.values():
        if existing["code"] == code:
            raise bad_request("Field 'code' must be unique across all terms.")
        if existing["term_index"] == term_index:
            raise bad_request("Field 'term_index' must be unique across all terms.")
    if start_date >= end_date:
        raise ApiError("ERR_INVALID_TIME_WINDOW")

    term = {
        "code": code,
        "term_index": term_index,
        "term_type": term_type,
        "catalog_year": catalog_year,
        "start_date": st.fmt_instant(start_date),
        "end_date": st.fmt_instant(end_date),
        "full_time_credit_minimum": full_time_minimum,
        "is_apr_reporting_term": is_reporting,
        "apr_status": "OPEN",
        "apr_points_possible": 0,
        "apr_points_earned": 0,
        "squad_apr": None,
        "_start_dt": start_date,
        "_end_dt": end_date,
    }
    st.stamp_new(term)
    st.terms[term["id"]] = term
    return h.created(term)


# --------------------------------------------------------- degree programs
@bp.get("/athletics/degree-programs/<degree_program_id>")
def get_program(degree_program_id):
    authenticate(PROGRAM_READ)
    return h.ok(h.program_or_404(degree_program_id))


@bp.get("/athletics/degree-programs")
def list_programs():
    authenticate(PROGRAM_READ)
    return h.listing(h.sorted_programs(), ("catalog_year",))


@bp.post("/athletics/degree-programs")
def create_program():
    authenticate(["Registrar"])
    body = json_body()
    code = want_string(body, "code")
    name = want_string(body, "name")
    catalog_year = want_int(body, "catalog_year")
    total_required = want_decimal(body, "total_required_credits")
    if total_required <= 0:
        raise bad_request("Field 'total_required_credits' must be greater than zero.")
    min_gpa = want_decimal(body, "min_progress_gpa", required=False,
                           default=Decimal("2.0"), minimum=0, maximum=4)
    deadline_terms = want_int(body, "major_declaration_deadline_term_count",
                              required=False, default=4, minimum=1)
    max_elective = want_decimal(body, "max_elective_credits_countable",
                                required=False, default=Decimal("12"), minimum=0)
    for existing in st.degree_programs.values():
        if existing["code"] == code:
            raise bad_request("Field 'code' must be unique across all degree programs.")

    program = {
        "code": code,
        "name": name,
        "catalog_year": catalog_year,
        "total_required_credits": q2(total_required),
        "min_progress_gpa": q2(min_gpa),
        "major_declaration_deadline_term_count": deadline_terms,
        "max_elective_credits_countable": q2(max_elective),
    }
    st.stamp_new(program)
    st.degree_programs[program["id"]] = program
    return h.created(program)


# ----------------------------------------------------------------- courses
@bp.get("/athletics/courses/<course_id>")
def get_course(course_id):
    authenticate(COURSE_READ)
    return h.ok(h.course_or_404(course_id))


@bp.get("/athletics/courses")
def list_courses():
    authenticate(COURSE_READ)
    return h.listing(h.sorted_courses(), ("subject_code", "is_remedial"))


@bp.post("/athletics/courses")
def create_course():
    authenticate(["Registrar"])
    body = json_body()
    subject_code = want_string(body, "subject_code")
    course_number = want_string(body, "course_number")
    title = want_string(body, "title")
    credit_hours = want_decimal(body, "credit_hours", maximum=12)
    if credit_hours <= 0:
        raise bad_request("Field 'credit_hours' must be greater than zero.")
    instructor_user_id = want_string(body, "instructor_user_id")
    is_remedial = want_bool(body, "is_remedial", default=False)
    meeting_days = want_int_list(body, "meeting_days", default=[], minimum=1, maximum=7)
    meeting_start = want_int(body, "meeting_start_minute_utc", required=False,
                             default=600, minimum=0, maximum=1439)
    meeting_duration = want_int(body, "meeting_duration_minutes", required=False,
                                default=50, maximum=480)
    if meeting_duration <= 0:
        raise bad_request("Field 'meeting_duration_minutes' must be greater than zero.")
    for existing in st.courses.values():
        if (existing["subject_code"] == subject_code
                and existing["course_number"] == course_number):
            raise bad_request(
                "The pair (subject_code, course_number) must be unique."
            )

    course = {
        "subject_code": subject_code,
        "course_number": course_number,
        "title": title,
        "credit_hours": q2(credit_hours),
        "is_remedial": is_remedial,
        "meeting_days": meeting_days,
        "meeting_start_minute_utc": meeting_start,
        "meeting_duration_minutes": meeting_duration,
        "instructor_user_id": instructor_user_id,
    }
    st.stamp_new(course)
    st.courses[course["id"]] = course
    return h.created(course)


# ---------------------------------------------- degree-applicability rules
@bp.get("/athletics/degree-applicability-rules/<rule_id>")
def get_rule(rule_id):
    authenticate(RULE_READ)
    return h.ok(h.rule_or_404(rule_id))


@bp.get("/athletics/degree-applicability-rules")
def list_rules():
    authenticate(RULE_READ)
    return h.listing(
        h.sorted_rules(),
        ("degree_program_id", "course_id", "effective_catalog_year", "applicability"),
    )


@bp.post("/athletics/degree-applicability-rules")
def create_rule():
    authenticate(["Registrar"])
    body = json_body()
    program = h.body_fk(body, "degree_program_id", h.program_or_404)
    course = h.body_fk(body, "course_id", h.course_or_404)
    program_id = want_string(body, "degree_program_id")
    course_id = want_string(body, "course_id")
    effective_year = want_int(body, "effective_catalog_year")
    applicability = want_enum(body, "applicability", calc.APPLICABILITY)
    max_countable = want_decimal(body, "max_countable_credits", required=False,
                                 default=None, minimum=0)
    if program is None:
        h.program_or_404(program_id)
    if course is None:
        h.course_or_404(course_id)
    for existing in st.rules.values():
        if (existing["degree_program_id"] == program_id
                and existing["course_id"] == course_id
                and existing["effective_catalog_year"] == effective_year):
            raise ApiError("ERR_DUPLICATE_APPLICABILITY_RULE")

    rule = {
        "degree_program_id": program_id,
        "course_id": course_id,
        "effective_catalog_year": effective_year,
        "applicability": applicability,
        "max_countable_credits": (q2(max_countable)
                                  if max_countable is not None else None),
    }
    st.stamp_new(rule)
    st.rules[rule["id"]] = rule

    # PRD 3.1: publishing a rule re-runs the chain for every student declared
    # into the rule's program, in created_at ascending order.
    for student in st.by_created(list(st.students.values())):
        if student.get("declared_program_id") == program_id:
            derive.recompute_student(student)
    return h.created(rule)
