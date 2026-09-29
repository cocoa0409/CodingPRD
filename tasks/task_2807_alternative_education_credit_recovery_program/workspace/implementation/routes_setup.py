"""District setup: home schools, centers, catalog, rosters, plans, clock."""
from flask import Blueprint

import derive
import validate as v
from auth import endpoint, scope_center, scope_school
from envelope import created, ok, ok_list
from errors import ApiError
from helpers import (eq, get_center, get_course, get_home_school, get_plan,
                     get_prior_record, get_student, q, q_bool, q_int)
from services import rederive_center
from store import D, fmt_ts, new_row, num, ordered, store, touch

bp = Blueprint("setup", __name__)

SUBJECT_AREAS = ("ELA", "MATH", "SCIENCE", "SOCIAL_STUDIES", "ELECTIVE")
MODALITIES = ("ONLINE", "PACKET", "BLENDED")
OUTCOMES = ("FAILED", "PASSED", "INCOMPLETE")
REPLACEMENT_POLICIES = ("REPLACE_ON_RECOVERY", "AVERAGE_ON_RECOVERY")


# ------------------------------------------------------------ home schools
@bp.post("/home-schools")
@endpoint("DistrictAdmin")
def create_home_school(ctx):
    b = v.body()
    row = new_row(
        name=v.req_str(b, "name", 1, 120),
        district_code=v.req_str(b, "district_code", 1, 20),
        accountability_cohort_year=v.req_int(b, "accountability_cohort_year", 2000, 2100),
    )
    store.home_schools[row["id"]] = row
    return created(derive.ser_home_school(row))


@bp.get("/home-schools/<home_school_id>")
@endpoint("DistrictAdmin", "HomeSchoolCounselor", "PlacementCoordinator", "Registrar")
def read_home_school(ctx, home_school_id):
    row = get_home_school(home_school_id)
    scope_school(ctx, row["id"])
    return ok(derive.ser_home_school(row))


@bp.get("/home-schools")
@endpoint("DistrictAdmin", "Registrar")
def list_home_schools(ctx):
    rows = ordered(store.home_schools.values())
    rows = eq(rows, "district_code", q("district_code"))
    flag = q("cohort_flag")
    if flag is not None:
        rows = [r for r in rows if derive.cohort_figures(r)["cohort_flag"] == flag]
    return ok_list(rows, derive.ser_home_school)


# ----------------------------------------------------------------- centers
@bp.post("/centers")
@endpoint("DistrictAdmin")
def create_center(ctx):
    b = v.body()
    row = new_row(
        name=v.req_str(b, "name", 1, 120),
        seat_capacity=v.req_int(b, "seat_capacity", 1, None),
        certified_teacher_fte=v.req_num(b, "certified_teacher_fte", exclusive_lo=0, dp=2),
        support_staff_fte=v.req_num(b, "support_staff_fte", lo=0, dp=2),
        max_students_per_teacher=v.req_int(b, "max_students_per_teacher", 1, None),
    )
    store.centers[row["id"]] = row
    return created(derive.ser_center(row))


@bp.get("/centers/<center_id>")
@endpoint("DistrictAdmin", "PlacementCoordinator", "HomeSchoolCounselor", "Registrar",
          "AltEdTeacher")
def read_center(ctx, center_id):
    row = get_center(center_id)
    scope_center(ctx, row["id"])
    return ok(derive.ser_center(row))


@bp.get("/centers")
@endpoint("DistrictAdmin", "HomeSchoolCounselor", "Registrar")
def list_centers(ctx):
    rows = ordered(store.centers.values())
    posture = q("intake_posture")
    if posture is not None:
        rows = [r for r in rows if derive.center_posture(r) == posture]
    return ok_list(rows, derive.ser_center)


@bp.patch("/centers/<center_id>/staffing")
@endpoint("DistrictAdmin")
def patch_staffing(ctx, center_id):
    center = get_center(center_id)
    b = v.body()
    fte = v.opt_num(b, "certified_teacher_fte", exclusive_lo=0, dp=2)
    support = v.opt_num(b, "support_staff_fte", lo=0, dp=2)
    cap = v.opt_int(b, "max_students_per_teacher", 1, None)
    expected = v.req_int(b, "expected_center_version")
    if expected != center["version"]:
        raise ApiError("ERR_STALE_CENTER_VERSION",
                       "expected_center_version does not match the center")
    new_fte = center["certified_teacher_fte"] if fte is None else fte
    new_cap = center["max_students_per_teacher"] if cap is None else cap
    active = derive.active_count_of_center(center["id"])
    if derive.staffing_headroom_for(new_fte, new_cap, active) < 0:
        raise ApiError("ERR_STAFFING_RATIO_EXCEEDED",
                       "the revision would drive staffing_headroom below zero")
    old_posture = derive.center_posture(center)
    if fte is not None:
        center["certified_teacher_fte"] = fte
    if support is not None:
        center["support_staff_fte"] = support
    if cap is not None:
        center["max_students_per_teacher"] = cap
    touch(center)
    rederive_center(center, old_posture)
    return ok(derive.ser_center(center))


# ----------------------------------------------------------------- courses
@bp.post("/courses")
@endpoint("DistrictAdmin")
def create_course(ctx):
    b = v.body()
    code = v.req_str(b, "code", 2, 16)
    title = v.req_str(b, "title", 1, 120)
    subject_area = v.req_enum(b, "subject_area", SUBJECT_AREAS)
    credit_value = v.req_num(b, "credit_value", lo="0.25", hi="2.00", step="0.25")
    modality = v.req_enum(b, "modality", MODALITIES)
    total_modules = v.req_int(b, "total_modules", 1, None)
    required_seat_hours = v.req_num(b, "required_seat_hours", exclusive_lo=0, dp=2)
    pacing_days = v.req_int(b, "pacing_days", 1, None)
    proctoring_required = v.req_bool(b, "proctoring_required")
    weight = v.opt_num(b, "proctored_exam_weight", lo="0.00", hi="0.60", dp=2,
                       default=D("0.40"))
    ncaa_approved = v.req_bool(b, "ncaa_approved")
    min_passing = v.opt_num(b, "min_passing_percent", lo=0, hi=100, default=D("60.00"))
    if modality in ("ONLINE", "BLENDED") and not proctoring_required:
        v.bad("proctoring_required must be true for ONLINE and BLENDED courses")
    for other in store.courses.values():
        if other["code"] == code:
            raise ApiError("ERR_DUPLICATE_COURSE_CODE",
                           "course code %s already exists" % code)
    row = new_row(
        code=code, title=title, subject_area=subject_area, credit_value=credit_value,
        modality=modality, total_modules=total_modules,
        required_seat_hours=required_seat_hours, pacing_days=pacing_days,
        proctoring_required=proctoring_required, proctored_exam_weight=weight,
        ncaa_approved=ncaa_approved, min_passing_percent=min_passing,
    )
    store.courses[row["id"]] = row
    return created(derive.ser_course(row))


@bp.get("/courses/<course_id>")
@endpoint("DistrictAdmin", "Registrar", "AltEdTeacher", "PlacementCoordinator",
          "HomeSchoolCounselor")
def read_course(ctx, course_id):
    return ok(derive.ser_course(get_course(course_id)))


@bp.get("/courses")
@endpoint("DistrictAdmin", "Registrar", "AltEdTeacher", "PlacementCoordinator")
def list_courses(ctx):
    rows = ordered(store.courses.values())
    rows = eq(rows, "subject_area", q("subject_area"))
    rows = eq(rows, "modality", q("modality"))
    rows = eq(rows, "ncaa_approved", q_bool("ncaa_approved"))
    return ok_list(rows, derive.ser_course)


# ---------------------------------------------------------------- students
@bp.post("/students")
@endpoint("DistrictAdmin", "Registrar")
def create_student(ctx):
    b = v.body()
    home_school_id = v.req_str(b, "home_school_id", 1, None)
    state_student_id = v.req_str(b, "state_student_id", 1, 32)
    full_name = v.req_str(b, "full_name", 1, 120)
    cohort_year = v.req_int(b, "cohort_year", 2000, 2100)
    grade_level = v.req_int(b, "grade_level", choices=(9, 10, 11, 12))
    get_home_school(home_school_id)
    for other in store.students.values():
        if other["state_student_id"] == state_student_id:
            raise ApiError("ERR_DUPLICATE_STATE_STUDENT_ID",
                           "state_student_id %s already exists" % state_student_id)
    row = new_row(home_school_id=home_school_id, state_student_id=state_student_id,
                  full_name=full_name, cohort_year=cohort_year, grade_level=grade_level)
    store.students[row["id"]] = row
    return created(derive.ser_student(row))


@bp.get("/students/<student_id>")
@endpoint("DistrictAdmin", "Registrar", "HomeSchoolCounselor", "PlacementCoordinator",
          "AltEdTeacher")
def read_student(ctx, student_id):
    row = get_student(student_id)
    scope_school(ctx, row["home_school_id"])
    return ok(derive.ser_student(row))


@bp.get("/students")
@endpoint("DistrictAdmin", "Registrar", "HomeSchoolCounselor")
def list_students(ctx):
    rows = ordered(store.students.values())
    if ctx.role == "HomeSchoolCounselor":
        rows = [r for r in rows if r["home_school_id"] == ctx.uid]
    rows = eq(rows, "home_school_id", q("home_school_id"))
    rows = eq(rows, "cohort_year", q_int("cohort_year"))
    status = q("status")
    if status is not None:
        rows = [r for r in rows if derive.student_status(r) == status]
    return ok_list(rows, derive.ser_student)


# --------------------------------------------------- prior course records
@bp.post("/prior-course-records")
@endpoint("Registrar")
def create_prior_record(ctx):
    b = v.body()
    student_id = v.req_str(b, "student_id", 1, None)
    course_id = v.req_str(b, "course_id", 1, None)
    term_code = v.req_str(b, "term_code", 1, 16)
    original_percent = v.req_num(b, "original_percent", lo=0, hi=100, dp=2)
    credits_attempted = v.req_num(b, "credits_attempted", lo="0.25", hi="2.00",
                                  step="0.25")
    outcome = v.req_enum(b, "outcome", OUTCOMES)
    get_student(student_id)
    get_course(course_id)
    row = new_row(student_id=student_id, course_id=course_id, term_code=term_code,
                  original_percent=original_percent,
                  credits_attempted=credits_attempted, outcome=outcome,
                  replacement_status="NOT_REPLACED")
    store.prior_records[row["id"]] = row
    return created(derive.ser_prior_record(row))


@bp.get("/prior-course-records/<prior_course_record_id>")
@endpoint("Registrar", "DistrictAdmin", "AltEdTeacher", "PlacementCoordinator")
def read_prior_record(ctx, prior_course_record_id):
    return ok(derive.ser_prior_record(get_prior_record(prior_course_record_id)))


@bp.get("/prior-course-records")
@endpoint("Registrar", "DistrictAdmin", "AltEdTeacher", "PlacementCoordinator")
def list_prior_records(ctx):
    rows = ordered(store.prior_records.values())
    rows = eq(rows, "student_id", q("student_id"))
    rows = eq(rows, "course_id", q("course_id"))
    rows = eq(rows, "outcome", q("outcome"))
    rows = eq(rows, "replacement_status", q("replacement_status"))
    return ok_list(rows, derive.ser_prior_record)


# -------------------------------------------------------- graduation plans
@bp.post("/graduation-plans")
@endpoint("Registrar")
def create_plan(ctx):
    b = v.body()
    student_id = v.req_str(b, "student_id", 1, None)
    required_credits_total = v.req_num(b, "required_credits_total", lo="0.25",
                                       hi="40.00", step="0.25")
    policy = v.req_enum(b, "grade_replacement_policy", REPLACEMENT_POLICIES)
    term = v.opt_str(b, "projected_completion_term", 1, 16)
    get_student(student_id)
    if derive.plan_of_student(student_id) is not None:
        raise ApiError("ERR_DUPLICATE_PLAN", "the student already has a plan")
    row = new_row(student_id=student_id,
                  required_credits_total=required_credits_total,
                  grade_replacement_policy=policy, projected_completion_term=term,
                  status="DRAFT")
    store.plans[row["id"]] = row
    return created(derive.ser_plan(row))


@bp.get("/graduation-plans/<graduation_plan_id>")
@endpoint("Registrar", "DistrictAdmin", "HomeSchoolCounselor", "PlacementCoordinator")
def read_plan(ctx, graduation_plan_id):
    row = get_plan(graduation_plan_id)
    student = store.students.get(row["student_id"])
    if student is not None:
        scope_school(ctx, student["home_school_id"])
    return ok(derive.ser_plan(row))


@bp.get("/graduation-plans")
@endpoint("Registrar", "DistrictAdmin", "HomeSchoolCounselor")
def list_plans(ctx):
    rows = ordered(store.plans.values())
    if ctx.role == "HomeSchoolCounselor":
        rows = [r for r in rows
                if store.students[r["student_id"]]["home_school_id"] == ctx.uid]
    rows = eq(rows, "student_id", q("student_id"))
    rows = eq(rows, "status", q("status"))
    posture = q("posture")
    if posture is not None:
        rows = [r for r in rows if derive.plan_posture(r) == posture]
    return ok_list(rows, derive.ser_plan)


@bp.post("/graduation-plans/<graduation_plan_id>/activate")
@endpoint("Registrar")
def activate_plan(ctx, graduation_plan_id):
    plan = get_plan(graduation_plan_id)
    b = v.body()
    term = v.opt_str(b, "projected_completion_term", 1, 16)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_STATE_INVALID", "only a DRAFT plan may be activated")
    plan["status"] = "ACTIVE"
    if term is not None:
        plan["projected_completion_term"] = term
    touch(plan)
    return ok(derive.ser_plan(plan))


# ------------------------------------------------------------ logical clock
@bp.post("/_clock/set_current_utc")
@endpoint("DistrictAdmin")
def set_clock(ctx):
    b = v.body()
    current = v.req_dt(b, "current_utc")
    if current < store.clock:
        raise ApiError("ERR_CLOCK_BACKWARD", "the logical clock may only move forward")
    store.clock = current
    return ok({"current_utc": fmt_ts(store.clock)})
