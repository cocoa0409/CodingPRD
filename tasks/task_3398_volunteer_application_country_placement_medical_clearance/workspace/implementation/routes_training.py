"""Training cohorts (aggregate overlap capacity) and enrollments
(enroll / assess / remediate / swear-in)."""
from datetime import timedelta
from flask import Blueprint, request

from authz import auth, require_roles
from calc import D
from cascade import accepted_invitation_of, legal_overall, separate_trainee
from db import (CULTURAL_MIN_SCORE, ROLES, SERVICE_TERM_DAYS, STORE,
                TECHNICAL_MIN_SCORE, fmt_ts, logical_now, new_record,
                parse_dt, touch, ts_sec)
from errors import err, ok_object, paginate
from validate import as_dt, as_int, as_number, as_str, body

bp = Blueprint("training", __name__)


def get_cohort_or_404(cid):
    cohort = STORE["training_cohorts"].get(cid)
    if cohort is None:
        err("ERR_COHORT_NOT_FOUND", 404, "Training cohort not found")
    return cohort


def get_enrollment_or_404(eid):
    enrollment = STORE["training_enrollments"].get(eid)
    if enrollment is None:
        err("ERR_ENROLLMENT_NOT_FOUND", 404, "Training enrollment not found")
    return enrollment


# --- TrainingCohort ----------------------------------------------------------
@bp.post("/volunteer-portal/training-cohorts")
def create_cohort():
    auth()
    require_roles(request.headers.get("X-User-Role"), ("SystemAdmin",))
    data = body()
    program = None
    if data.get("country_program_id") is not None:
        program = STORE["country_programs"].get(data["country_program_id"])
        if program is None:
            err("ERR_PROGRAM_NOT_FOUND", 404, "Country program not found")
    # Aggregate overlap capacity (priority 8): half-open windows; overlapping
    # SCHEDULED/IN_SESSION cohorts of the same program share a capacity budget.
    start = parse_dt(data.get("start_date"))
    end = parse_dt(data.get("end_date"))
    capacity = data.get("capacity")
    if (program is not None and start is not None and end is not None
            and isinstance(capacity, int) and not isinstance(capacity, bool)):
        overlapping = 0
        for other in STORE["training_cohorts"].values():
            if (other["country_program_id"] != program["id"]
                    or other["status"] not in ("SCHEDULED", "IN_SESSION")):
                continue
            o_start = parse_dt(other["start_date"])
            o_end = parse_dt(other["end_date"])
            if ts_sec(start) < ts_sec(o_end) and ts_sec(o_start) < ts_sec(end):
                overlapping += other["capacity"]
        if capacity + overlapping > program["training_capacity"]:
            err("ERR_TRAINING_CAPACITY_EXCEEDED", 409,
                "Overlapping cohort capacity %d + %d exceeds program "
                "training_capacity %d"
                % (capacity, overlapping, program["training_capacity"]))
    # Field shape (priority 10)
    program_id = as_str(data, "country_program_id")
    name = as_str(data, "name")
    start = as_dt(data, "start_date")
    end = as_dt(data, "end_date")
    if ts_sec(end) <= ts_sec(start):
        err("ERR_VALIDATION", 400, "end_date must be strictly after start_date")
    capacity = as_int(data, "capacity", minimum=1)
    rec = new_record()
    rec.update({
        "country_program_id": program_id,
        "name": name,
        "start_date": fmt_ts(start),
        "end_date": fmt_ts(end),
        "capacity": capacity,
        "enrolled_count": 0,
        "status": "SCHEDULED",
    })
    STORE["training_cohorts"][rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/volunteer-portal/training-cohorts/<cid>")
def get_cohort(cid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    return ok_object(get_cohort_or_404(cid))


@bp.get("/volunteer-portal/training-cohorts")
def list_cohorts():
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    args = request.args
    records = sorted(STORE["training_cohorts"].values(),
                     key=lambda r: r["created_at"])
    if args.get("country_program_id") is not None:
        records = [r for r in records
                   if r["country_program_id"] == args["country_program_id"]]
    if args.get("status") is not None:
        records = [r for r in records if r["status"] == args["status"]]
    return paginate(records)


# --- TrainingEnrollment ------------------------------------------------------
@bp.post("/volunteer-portal/training-enrollments")
def create_enrollment():
    auth()
    require_roles(request.headers.get("X-User-Role"), ("PlacementOfficer",))
    data = body()
    application = None
    if data.get("application_id") is not None:
        application = STORE["applications"].get(data["application_id"])
        if application is None:
            err("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    cohort = None
    if data.get("training_cohort_id") is not None:
        cohort = STORE["training_cohorts"].get(data["training_cohort_id"])
        if cohort is None:
            err("ERR_COHORT_NOT_FOUND", 404, "Training cohort not found")
    # State guards (priority 6)
    if application is not None and application["status"] != "ACCEPTED":
        err("ERR_INVALID_APPLICATION_STATE", 409,
            "enrollment requires ACCEPTED, found %s" % application["status"])
    if cohort is not None and cohort["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409,
            "enrollment requires a SCHEDULED cohort, found %s" % cohort["status"])
    # Compliance gate (priority 7): both clearances cleared.
    if application is not None:
        medical_ok = any(
            mc["status"] in ("CLEARED", "CLEARED_WITH_ACCOMMODATION")
            for mc in STORE["medical_clearances"].values()
            if mc["application_id"] == application["id"])
        legal_ok = any(
            legal_overall(lc) == "CLEARED"
            for lc in STORE["legal_clearances"].values()
            if lc["application_id"] == application["id"])
        if not (medical_ok and legal_ok):
            err("ERR_CLEARANCES_NOT_CLEARED", 422,
                "Enrollment requires medical CLEARED/CLEARED_WITH_ACCOMMODATION "
                "and legal overall_status CLEARED")
    # Business constraints (priority 8): pinned program match, then capacity.
    if application is not None and cohort is not None:
        invitation = accepted_invitation_of(application["id"])
        pinned = (invitation["pinned_country_program_id"]
                  if invitation is not None else None)
        if cohort["country_program_id"] != pinned:
            err("ERR_COHORT_PROGRAM_MISMATCH", 422,
                "Cohort belongs to a different program than the invitation's "
                "pinned_country_program_id")
        if cohort["enrolled_count"] >= cohort["capacity"]:
            err("ERR_COHORT_CAPACITY_EXCEEDED", 409,
                "Cohort enrolled_count has reached capacity")
    # Field shape (priority 10)
    application_id = as_str(data, "application_id")
    cohort_id = as_str(data, "training_cohort_id")
    if application is None:
        application = STORE["applications"][application_id]
    if cohort is None:
        cohort = STORE["training_cohorts"][cohort_id]
    rec = new_record()
    rec.update({
        "application_id": application_id,
        "training_cohort_id": cohort_id,
        "assessment_attempts": 0,
        "language_score": None,
        "technical_score": None,
        "cultural_score": None,
        "status": "ENROLLED",
    })
    STORE["training_enrollments"][rec["id"]] = rec
    cohort["enrolled_count"] += 1
    touch(cohort)
    application["status"] = "CLEARED_TO_DEPART"
    touch(application)
    return ok_object(rec, 201)


@bp.get("/volunteer-portal/training-enrollments/<eid>")
def get_enrollment(eid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    return ok_object(get_enrollment_or_404(eid))


@bp.get("/volunteer-portal/training-enrollments")
def list_enrollments():
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    args = request.args
    records = sorted(STORE["training_enrollments"].values(),
                     key=lambda r: r["created_at"])
    if args.get("application_id") is not None:
        records = [r for r in records if r["application_id"] == args["application_id"]]
    if args.get("training_cohort_id") is not None:
        records = [r for r in records
                   if r["training_cohort_id"] == args["training_cohort_id"]]
    if args.get("status") is not None:
        records = [r for r in records if r["status"] == args["status"]]
    return paginate(records)


@bp.post("/volunteer-portal/training-enrollments/<eid>/assess")
def assess_enrollment(eid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("TrainingDirector",))
    enrollment = get_enrollment_or_404(eid)
    cohort = STORE["training_cohorts"].get(enrollment["training_cohort_id"])
    # State guards (priority 6): cohort IN_SESSION, then enrollment assessable.
    if cohort is None or cohort["status"] != "IN_SESSION":
        err("ERR_INVALID_STATE", 409, "assess requires the cohort IN_SESSION")
    if enrollment["status"] not in ("ENROLLED", "REMEDIATION"):
        err("ERR_ENROLLMENT_NOT_ASSESSABLE", 409,
            "assess requires ENROLLED or REMEDIATION, found %s"
            % enrollment["status"])
    data = body()
    language = as_number(data, "language_score", minimum=1.0, maximum=5.0)
    technical = as_number(data, "technical_score", minimum=1.0, maximum=5.0)
    cultural = as_number(data, "cultural_score", minimum=1.0, maximum=5.0)
    program = STORE["country_programs"].get(cohort["country_program_id"])
    threshold = program["language_threshold_score"] if program is not None else 5.0
    passed = (D(language) >= D(threshold)
              and D(technical) >= D(TECHNICAL_MIN_SCORE)
              and D(cultural) >= D(CULTURAL_MIN_SCORE))
    enrollment["assessment_attempts"] += 1
    enrollment["language_score"] = language
    enrollment["technical_score"] = technical
    enrollment["cultural_score"] = cultural
    if enrollment["status"] == "ENROLLED":
        enrollment["status"] = "PASSED" if passed else "FAILED"
        touch(enrollment)
    else:  # REMEDIATION — second and final attempt
        if passed:
            enrollment["status"] = "PASSED"
            touch(enrollment)
        else:
            separate_trainee(enrollment)
    return ok_object(enrollment)


@bp.post("/volunteer-portal/training-enrollments/<eid>/remediate")
def remediate_enrollment(eid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("TrainingDirector",))
    enrollment = get_enrollment_or_404(eid)
    if enrollment["status"] != "FAILED":
        err("ERR_ENROLLMENT_NOT_ASSESSABLE", 409,
            "remediate requires FAILED, found %s" % enrollment["status"])
    enrollment["status"] = "REMEDIATION"
    touch(enrollment)
    return ok_object(enrollment)


@bp.post("/volunteer-portal/training-enrollments/<eid>/swear-in")
def swear_in_enrollment(eid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("TrainingDirector",))
    enrollment = get_enrollment_or_404(eid)
    if enrollment["status"] != "PASSED":
        err("ERR_ENROLLMENT_NOT_ASSESSABLE", 409,
            "swear-in requires PASSED, found %s" % enrollment["status"])
    enrollment["status"] = "SWORN_IN"
    touch(enrollment)
    app = STORE["applications"].get(enrollment["application_id"])
    invitation = accepted_invitation_of(enrollment["application_id"])
    start = logical_now()
    service = new_record()
    service.update({
        "application_id": enrollment["application_id"],
        "assignment_opening_id": (invitation["assignment_opening_id"]
                                  if invitation is not None else None),
        "country_program_id": (invitation["pinned_country_program_id"]
                               if invitation is not None else None),
        "service_start_date": fmt_ts(start),
        "expected_completion_date": fmt_ts(start + timedelta(days=SERVICE_TERM_DAYS)),
        "actual_end_date": None,
        "days_served": None,
        "months_served": None,
        "status": "ACTIVE",
    })
    STORE["volunteer_services"][service["id"]] = service
    if app is not None and app["status"] == "IN_TRAINING":
        app["status"] = "SWORN_IN"
        touch(app)
    return ok_object(enrollment)
