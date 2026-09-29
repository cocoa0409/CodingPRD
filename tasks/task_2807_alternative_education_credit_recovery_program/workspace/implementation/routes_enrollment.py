"""Course enrollments: recovery eligibility, progress, award and integrity."""
from flask import Blueprint

import derive
import validate as v
from auth import endpoint, scope_center
from envelope import created, ok, ok_list
from errors import ApiError
from helpers import (eq, get_course, get_enrollment, get_placement,
                     get_prior_record, q)
from services import post_award, void_award
from store import D, dmin, new_row, ordered, store, touch

bp = Blueprint("enrollments", __name__)

ENROLLMENT_TYPES = ("CREDIT_RECOVERY", "NEW_CREDIT")
RESOLUTIONS = ("CLEARED", "VOIDED_FOR_INTEGRITY")
AWARDABLE_INTEGRITY = ("CLEAR", "CLEARED")


def _placement_of(enrollment):
    return store.placements[enrollment["placement_id"]]


def _center_scope(ctx, enrollment):
    scope_center(ctx, _placement_of(enrollment)["center_id"])


@bp.post("/course-enrollments")
@endpoint("AltEdTeacher")
def create_enrollment(ctx):
    b = v.body()
    placement_id = v.req_str(b, "placement_id", 1, None)
    course_id = v.req_str(b, "course_id", 1, None)
    enrollment_type = v.req_enum(b, "enrollment_type", ENROLLMENT_TYPES)
    prior_record_id = v.opt_str(b, "prior_course_record_id", 1, None)
    expected = v.req_int(b, "expected_placement_version")
    placement = get_placement(placement_id)
    course = get_course(course_id)
    prior_record = get_prior_record(prior_record_id) if prior_record_id else None
    if expected != placement["version"]:
        raise ApiError("ERR_STALE_PLACEMENT_VERSION",
                       "expected_placement_version does not match the placement")
    # rung 11 -- uniqueness
    for other in derive.enrollments_of_placement(placement_id):
        if other["course_id"] == course_id and \
                other["progress_state"] != "AWARD_DENIED":
            raise ApiError("ERR_DUPLICATE_ENROLLMENT",
                           "the placement already holds an enrollment in this course")
    if prior_record is not None:
        for other in store.enrollments.values():
            if other["prior_course_record_id"] == prior_record_id and \
                    other["progress_state"] in derive.IN_FLIGHT_PROGRESS_STATES:
                raise ApiError("ERR_PRIOR_RECORD_ALREADY_ENROLLED",
                               "the historical row already backs an in-flight attempt")
    # rung 13 -- catalog and recovery eligibility
    if enrollment_type == "CREDIT_RECOVERY":
        if prior_record is None:
            raise ApiError("ERR_MISSING_PRIOR_RECORD",
                           "a credit-recovery enrollment requires prior_course_record_id")
        if prior_record["outcome"] != "FAILED":
            raise ApiError("ERR_COURSE_NOT_PREVIOUSLY_FAILED",
                           "only a previously FAILED course may be recovered")
        if prior_record["student_id"] != placement["student_id"] or \
                prior_record["course_id"] != course_id:
            raise ApiError("ERR_PRIOR_RECORD_MISMATCH",
                           "the historical row belongs to another student or course")
        if prior_record["replacement_status"] != "NOT_REPLACED":
            raise ApiError("ERR_PRIOR_RECORD_ALREADY_REPLACED",
                           "the historical row has already been replaced")
    # rung 19 -- capacity
    center = store.centers[placement["center_id"]]
    if derive.center_posture(center) == "FROZEN":
        raise ApiError("ERR_INTAKE_FROZEN", "the center's intake posture is FROZEN")
    row = new_row(
        placement_id=placement_id, course_id=course_id,
        prior_course_record_id=prior_record_id, enrollment_type=enrollment_type,
        progress_state="IN_PROGRESS", integrity_state="CLEAR",
        enrolled_on=store.clock_date(), modules_passed=0, seat_hours_logged=D("0"),
        module_avg_percent=None, final_percent=None, submitted_by_user_id=None,
        integrity_incident_code=None, integrity_resolution_note=None,
        denial_reason=None,
    )
    store.enrollments[row["id"]] = row
    touch(placement)
    return created(derive.ser_enrollment(row))


@bp.get("/course-enrollments/<course_enrollment_id>")
@endpoint("AltEdTeacher", "Registrar", "PlacementCoordinator", "DistrictAdmin")
def read_enrollment(ctx, course_enrollment_id):
    row = get_enrollment(course_enrollment_id)
    _center_scope(ctx, row)
    return ok(derive.ser_enrollment(row))


@bp.get("/course-enrollments")
@endpoint("AltEdTeacher", "Registrar", "PlacementCoordinator", "DistrictAdmin")
def list_enrollments(ctx):
    rows = ordered(store.enrollments.values())
    if ctx.role == "PlacementCoordinator":
        rows = [r for r in rows if _placement_of(r)["center_id"] == ctx.uid]
    rows = eq(rows, "placement_id", q("placement_id"))
    rows = eq(rows, "course_id", q("course_id"))
    rows = eq(rows, "prior_course_record_id", q("prior_course_record_id"))
    rows = eq(rows, "progress_state", q("progress_state"))
    rows = eq(rows, "integrity_state", q("integrity_state"))
    return ok_list(rows, derive.ser_enrollment)


@bp.post("/course-enrollments/<course_enrollment_id>/progress")
@endpoint("AltEdTeacher")
def report_progress(ctx, course_enrollment_id):
    enrollment = get_enrollment(course_enrollment_id)
    b = v.body()
    modules_delta = v.opt_int(b, "modules_passed_delta", 0, None)
    seat_delta = v.opt_num(b, "seat_hours_delta", lo=0)
    module_avg = v.opt_num(b, "module_avg_percent")
    if enrollment["progress_state"] != "IN_PROGRESS":
        raise ApiError("ERR_ENROLLMENT_STATE_INVALID",
                       "progress may only be reported on an IN_PROGRESS enrollment")
    if enrollment["integrity_state"] == "FLAGGED":
        raise ApiError("ERR_INTEGRITY_HOLD", "the enrollment is FLAGGED")
    course = store.courses[enrollment["course_id"]]
    if modules_delta is not None:
        enrollment["modules_passed"] = min(
            course["total_modules"], enrollment["modules_passed"] + modules_delta)
    if seat_delta is not None:
        enrollment["seat_hours_logged"] = D(enrollment["seat_hours_logged"]) + seat_delta
    if module_avg is not None:
        enrollment["module_avg_percent"] = module_avg
    touch(enrollment)
    return ok(derive.ser_enrollment(enrollment))


@bp.post("/course-enrollments/<course_enrollment_id>/submit-for-award")
@endpoint("AltEdTeacher", "Registrar")
def submit_for_award(ctx, course_enrollment_id):
    enrollment = get_enrollment(course_enrollment_id)
    b = v.body()
    final_percent = v.req_num(b, "final_percent")
    if enrollment["progress_state"] != "IN_PROGRESS":
        raise ApiError("ERR_ENROLLMENT_STATE_INVALID",
                       "only an IN_PROGRESS enrollment may be submitted")
    placement = _placement_of(enrollment)
    if placement["status"] != "ACTIVE":
        raise ApiError("ERR_PLACEMENT_STATE_INVALID",
                       "the owning placement is not ACTIVE")
    if enrollment["integrity_state"] == "FLAGGED":
        raise ApiError("ERR_INTEGRITY_HOLD", "the enrollment is FLAGGED")
    course = store.courses[enrollment["course_id"]]
    if course["proctoring_required"] and \
            not derive.has_completed_session(enrollment["id"]):
        raise ApiError("ERR_PROCTORED_EXAM_MISSING",
                       "a COMPLETED proctored exam session is required")
    enrollment["progress_state"] = "SUBMITTED_FOR_AWARD"
    enrollment["final_percent"] = final_percent
    enrollment["submitted_by_user_id"] = ctx.uid
    touch(enrollment)
    return ok(derive.ser_enrollment(enrollment))


@bp.post("/course-enrollments/<course_enrollment_id>/award-credit")
@endpoint("Registrar")
def award_credit(ctx, course_enrollment_id):
    enrollment = get_enrollment(course_enrollment_id)
    b = v.body()
    expected = v.req_int(b, "expected_graduation_plan_version")
    if enrollment["submitted_by_user_id"] is not None and \
            ctx.uid == enrollment["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the submitting operator may not award the credit")
    placement = _placement_of(enrollment)
    plan = derive.plan_of_student(placement["student_id"])
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "the student has no graduation plan")
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION",
                       "expected_graduation_plan_version does not match the plan")
    if enrollment["progress_state"] != "SUBMITTED_FOR_AWARD":
        raise ApiError("ERR_ENROLLMENT_STATE_INVALID",
                       "only a SUBMITTED_FOR_AWARD enrollment may be awarded")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_STATE_INVALID", "the graduation plan is not ACTIVE")
    if enrollment["integrity_state"] not in AWARDABLE_INTEGRITY:
        raise ApiError("ERR_INTEGRITY_HOLD",
                       "the enrollment's integrity_state blocks the award")
    course = store.courses[enrollment["course_id"]]
    if enrollment["enrollment_type"] == "CREDIT_RECOVERY" and \
            enrollment["prior_course_record_id"]:
        record = store.prior_records[enrollment["prior_course_record_id"]]
        if record["replacement_status"] != "NOT_REPLACED":
            raise ApiError("ERR_PRIOR_RECORD_ALREADY_REPLACED",
                           "the historical row has already been replaced")
    # rung 18 -- academic gates, in their pinned internal order
    if D(enrollment["final_percent"]) < D(course["min_passing_percent"]):
        raise ApiError("ERR_FINAL_PERCENT_BELOW_PASSING",
                       "final_percent is below the course's min_passing_percent")
    credits = derive.computed_credits(enrollment, course, placement)
    if placement["credit_policy"] == "COMPETENCY":
        mastery = derive.mastery_pct(enrollment, course)
        if mastery is None or mastery < D("70.00") or credits <= 0:
            raise ApiError("ERR_MASTERY_NOT_MET",
                           "mastery_pct does not support a credit award")
    elif credits <= 0:
        raise ApiError("ERR_SEAT_TIME_INSUFFICIENT",
                       "the logged seat hours do not support a credit award")
    award = post_award(enrollment, course, placement, plan, credits)
    return created(derive.ser_award(award))


@bp.post("/course-enrollments/<course_enrollment_id>/deny-award")
@endpoint("Registrar")
def deny_award(ctx, course_enrollment_id):
    enrollment = get_enrollment(course_enrollment_id)
    b = v.body()
    reason = v.req_str(b, "denial_reason", 1, None)
    if enrollment["submitted_by_user_id"] is not None and \
            ctx.uid == enrollment["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the submitting operator may not deny the award")
    if enrollment["progress_state"] != "SUBMITTED_FOR_AWARD":
        raise ApiError("ERR_ENROLLMENT_STATE_INVALID",
                       "only a SUBMITTED_FOR_AWARD enrollment may be denied")
    enrollment["progress_state"] = "AWARD_DENIED"
    enrollment["denial_reason"] = reason
    touch(enrollment)
    return ok(derive.ser_enrollment(enrollment))


@bp.post("/course-enrollments/<course_enrollment_id>/flag-integrity")
@endpoint("PlacementCoordinator", "DistrictAdmin")
def flag_integrity(ctx, course_enrollment_id):
    enrollment = get_enrollment(course_enrollment_id)
    _center_scope(ctx, enrollment)
    b = v.body()
    code = v.req_str(b, "integrity_incident_code", 1, None)
    if enrollment["integrity_state"] != "CLEAR":
        raise ApiError("ERR_ENROLLMENT_STATE_INVALID",
                       "only a CLEAR enrollment may be flagged")
    enrollment["integrity_state"] = "FLAGGED"
    enrollment["integrity_incident_code"] = code
    touch(enrollment)
    return ok(derive.ser_enrollment(enrollment))


@bp.post("/course-enrollments/<course_enrollment_id>/resolve-integrity")
@endpoint("DistrictAdmin")
def resolve_integrity(ctx, course_enrollment_id):
    enrollment = get_enrollment(course_enrollment_id)
    b = v.body()
    resolution = v.req_enum(b, "resolution", RESOLUTIONS)
    note = v.opt_str(b, "integrity_resolution_note", 1, None)
    if enrollment["integrity_state"] != "FLAGGED":
        raise ApiError("ERR_ENROLLMENT_STATE_INVALID",
                       "only a FLAGGED enrollment may be resolved")
    enrollment["integrity_state"] = resolution
    if note is not None:
        enrollment["integrity_resolution_note"] = note
    if resolution == "VOIDED_FOR_INTEGRITY":
        award = derive.posted_award_of_enrollment(enrollment["id"])
        if award is not None:
            void_award(award, "INTEGRITY_VOID", touch_enrollment=False)
    touch(enrollment)
    return ok(derive.ser_enrollment(enrollment))
