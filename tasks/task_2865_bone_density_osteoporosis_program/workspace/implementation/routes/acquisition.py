"""Scan sessions, skeletal site measurements, the VFA add-on, submission and review."""
from flask import Blueprint, request

import calc
import queries
import validate
from db import base_record, db, now_iso, public, today, touch
from errors import ApiError
from middleware import (INTERPRETING_PHYSICIAN, PROGRAM_ADMIN, QUALITY_REVIEWER,
                        TECHNOLOGIST, actor_id, actor_role, endpoint)
from response import created, ok, paginated
from util import completed_years, dec

bp = Blueprint("acquisition", __name__)

SCAN_MODES = ("ARRAY", "FAST_ARRAY", "HIGH_DEFINITION")
SITE_CODES = ("LUMBAR_SPINE", "FEMORAL_NECK", "TOTAL_HIP", "FOREARM_33")
DEFECT_CODES = ("ROTATION_FEMUR", "ABDUCTION_FEMUR", "SPINE_NOT_STRAIGHT",
                "ARTIFACT_IN_FIELD", "INCORRECT_ROI", "MOTION_ARTIFACT",
                "INADEQUATE_SCAN_LENGTH")
PRIOR_ACQUISITION_STATUSES = ("SUBMITTED", "ARCHIVED")
PRIOR_REVIEW_STATUSES = ("ACCEPTED", "ACCEPTED_WITH_LIMITATION")


def _filtered(rows, filters):
    result = rows
    for param, field in filters.items():
        wanted = request.args.get(param)
        if wanted is not None and wanted != "":
            result = [row for row in result if str(row.get(field)) == wanted]
    return result


def _require_session_technologist(session):
    """Ladder 36: only the acquiring technologist may drive the session."""
    if actor_role() == TECHNOLOGIST and actor_id() != session["technologist_user_id"]:
        raise ApiError("ERR_NOT_SESSION_TECHNOLOGIST",
                       "Only the session's own technologist may perform this action.", 403)


def _candidate_priors(patient_id, exclude_session_id):
    pool = []
    for row in queries.sessions_of_patient(patient_id):
        if row["id"] == exclude_session_id:
            continue
        if row["acquisition_status"] not in PRIOR_ACQUISITION_STATUSES:
            continue
        if row["review_status"] not in PRIOR_REVIEW_STATUSES:
            continue
        if row["submitted_at_utc"] is None:
            continue
        finalized = [report for report in queries.reports_of_session(row["id"])
                     if report["status"] == "FINALIZED"]
        if not finalized:
            continue
        pool.append(row)
    return pool


@bp.post("/scan-appointments/<appointment_id>/scan-sessions")
@endpoint(TECHNOLOGIST)
def create_scan_session(appointment_id):
    body = validate.body()
    scan_mode = validate.enum(body, "scan_mode", SCAN_MODES)

    appointment = queries.appointment(appointment_id)
    device = queries.device(appointment["densitometer_id"])
    if device["status"] == "RETIRED":
        raise ApiError("ERR_DENSITOMETER_RETIRED", "The densitometer is retired.")
    if device["status"] != "ACTIVE":
        raise ApiError("ERR_DENSITOMETER_NOT_ACTIVE", "The densitometer is not ACTIVE.")
    if appointment["status"] != "BOOKED":
        raise ApiError("ERR_APPOINTMENT_NOT_BOOKED", "The appointment is not BOOKED.")
    if device["lsc_g_cm2"] is None:
        raise ApiError("ERR_DEVICE_PRECISION_NOT_CERTIFIED",
                       "The densitometer has no certified least significant change.")

    order = db.scan_orders[appointment["scan_order_id"]]
    patient_id = order["patient_id"]
    record = base_record()
    prior, comparison = calc.select_prior(
        _candidate_priors(patient_id, record["id"]),
        device["id"], device["calibration_generation"])
    record.update({
        "scan_appointment_id": appointment_id,
        "densitometer_id": device["id"],
        "patient_id": patient_id,
        "prior_session_id": None if prior is None else prior["id"],
        "prior_comparison_status": comparison,
        "technologist_user_id": actor_id(),
        "scan_mode": scan_mode,
        "calibration_generation": device["calibration_generation"],
        "applied_lsc_g_cm2": device["lsc_g_cm2"],
        "applied_cross_cal_factor": device["cross_cal_factor"],
        "acquisition_status": "IN_PROGRESS",
        "review_status": "NOT_REVIEWED",
        "repeat_count": 0,
        "submitted_at_utc": None,
        "vfa_performed": False,
        "vfa_eligibility_code": None,
        "vfa_max_genant_grade": None,
        "vfa_fracture_count": None,
        "measured_site_count": 0,
        "lowest_t_score": None,
        "lowest_t_score_site": None,
        "lowest_z_score": None,
    })
    db.scan_sessions[record["id"]] = record
    appointment["status"] = "CHECKED_IN"
    touch(appointment)
    return created(public(record))


@bp.get("/scan-sessions/<session_id>")
@endpoint(PROGRAM_ADMIN, TECHNOLOGIST, QUALITY_REVIEWER, INTERPRETING_PHYSICIAN)
def get_scan_session(session_id):
    return ok(public(queries.session(session_id)))


@bp.get("/scan-sessions")
@endpoint(PROGRAM_ADMIN, TECHNOLOGIST, QUALITY_REVIEWER, INTERPRETING_PHYSICIAN)
def list_scan_sessions():
    rows = _filtered(list(db.scan_sessions.values()), {
        "scan_appointment_id": "scan_appointment_id",
        "prior_session_id": "prior_session_id",
        "densitometer_id": "densitometer_id",
        "patient_id": "patient_id",
        "acquisition_status": "acquisition_status",
        "review_status": "review_status",
    })
    rows.sort(key=lambda row: (row["created_at"], row["_seq"]))
    return paginated(rows, public)


def _session_for_acquisition(session_id):
    """Ladder 26 then 30: IN_PROGRESS work, with ARCHIVED falling through."""
    session = queries.session(session_id)
    if session["acquisition_status"] not in ("IN_PROGRESS", "ARCHIVED"):
        raise ApiError("ERR_SESSION_NOT_IN_PROGRESS", "The session is not IN_PROGRESS.")
    if session["acquisition_status"] == "ARCHIVED":
        raise ApiError("ERR_SESSION_ARCHIVED", "The session is archived.")
    return session


def _refresh_measured_site_count(session):
    session["measured_site_count"] = len(queries.measurements(session["id"]))


@bp.post("/scan-sessions/<session_id>/site-measurements")
@endpoint(TECHNOLOGIST)
def create_site_measurement(session_id):
    body = validate.body()
    site_code = validate.enum(body, "site_code", SITE_CODES)
    bmd = validate.number(body, "bmd_g_cm2", minimum=0, maximum="2.5",
                          min_exclusive=True, max_places=4)
    area = validate.number(body, "area_cm2", minimum=0, maximum="200.0",
                           min_exclusive=True, max_places=2)
    bmc = validate.number(body, "bmc_g", minimum=0, maximum="400.0",
                          min_exclusive=True, max_places=2)
    reference_mean = validate.number(body, "reference_mean_bmd_g_cm2", minimum=0,
                                     maximum="2.5", min_exclusive=True, max_places=4)
    reference_sd = validate.number(body, "reference_sd_g_cm2", minimum=0, maximum="0.5",
                                   min_exclusive=True, max_places=4)
    age_matched_mean = validate.number(body, "age_matched_mean_bmd_g_cm2", minimum=0,
                                       maximum="2.5", min_exclusive=True, max_places=4)
    age_matched_sd = validate.number(body, "age_matched_sd_g_cm2", minimum=0,
                                     maximum="0.5", min_exclusive=True, max_places=4)
    if site_code == "LUMBAR_SPINE":
        vertebrae = validate.enum_array(body, "included_vertebrae", calc.LUMBAR_LEVELS,
                                        unique=False, non_empty=False)
    else:
        if validate.present(body, "included_vertebrae"):
            validate.bad("included_vertebrae is only accepted for LUMBAR_SPINE.")
        vertebrae = None

    session = _session_for_acquisition(session_id)
    _require_session_technologist(session)

    if site_code == "LUMBAR_SPINE":
        if len(set(vertebrae)) != len(vertebrae) or \
                len(vertebrae) < calc.MIN_VALID_VERTEBRAE:
            raise ApiError("ERR_INSUFFICIENT_VALID_VERTEBRAE",
                           "A lumbar spine row needs at least two distinct vertebral levels.",
                           422)
    if queries.measurement_at(session_id, site_code) is not None:
        raise ApiError("ERR_DUPLICATE_SITE_MEASUREMENT",
                       "A measurement for that site already exists on this session.")
    order = queries.order_of_session(session)
    if site_code not in order["requested_sites"]:
        raise ApiError("ERR_SITE_NOT_REQUESTED",
                       "That site does not appear in the order's requested_sites.")

    t_score, z_score, valid_count, usable = calc.site_scores(
        site_code, bmd, reference_mean, reference_sd,
        age_matched_mean, age_matched_sd, vertebrae)
    record = base_record(versioned=False)
    record.update({
        "scan_session_id": session_id,
        "site_code": site_code,
        "bmd_g_cm2": bmd,
        "area_cm2": area,
        "bmc_g": bmc,
        "reference_mean_bmd_g_cm2": reference_mean,
        "reference_sd_g_cm2": reference_sd,
        "age_matched_mean_bmd_g_cm2": age_matched_mean,
        "age_matched_sd_g_cm2": age_matched_sd,
        "included_vertebrae": vertebrae,
        "valid_vertebral_count": valid_count,
        "t_score": t_score,
        "z_score": z_score,
        "site_usable_for_diagnosis": usable,
        "superseded": False,
    })
    db.site_measurements[record["id"]] = record
    _refresh_measured_site_count(session)
    touch(session)
    return created(public(record))


@bp.get("/scan-sessions/<session_id>/site-measurements")
@endpoint(PROGRAM_ADMIN, TECHNOLOGIST, QUALITY_REVIEWER, INTERPRETING_PHYSICIAN)
def list_site_measurements(session_id):
    queries.session(session_id)
    include_superseded = validate.bool_param("include_superseded", False)
    rows = queries.measurements(session_id, include_superseded)
    rows = _filtered(rows, {"site_code": "site_code"})
    rows.sort(key=lambda row: (row["created_at"], row["_seq"]))
    return paginated(rows, public)


@bp.post("/scan-sessions/<session_id>/vfa")
@endpoint(TECHNOLOGIST)
def record_vfa(session_id):
    body = validate.body()
    grades = validate.int_array(body, "genant_grades", minimum=0, maximum=3)

    session = _session_for_acquisition(session_id)
    _require_session_technologist(session)
    order = queries.order_of_session(session)
    if not order["vfa_requested"]:
        raise ApiError("ERR_VFA_NOT_ORDERED",
                       "The owning order did not request a vertebral fracture assessment.")
    patient = db.patients[session["patient_id"]]
    policy = queries.policy_of(patient)
    profile = queries.active_profile(patient["id"])
    age_years = completed_years(patient["_birth_date"], today())
    eligibility = calc.vfa_eligibility(policy, profile, age_years)
    if eligibility == "NOT_ELIGIBLE":
        raise ApiError("ERR_VFA_NOT_ELIGIBLE",
                       "The patient meets no vertebral fracture assessment criterion.")
    if not policy["vfa_covered"]:
        raise ApiError("ERR_VFA_NOT_COVERED",
                       "The patient's policy does not cover vertebral fracture assessment.",
                       402)

    max_grade, fracture_count = calc.vfa_grading(grades)
    session["vfa_performed"] = True
    session["vfa_eligibility_code"] = eligibility
    session["vfa_max_genant_grade"] = max_grade
    session["vfa_fracture_count"] = fracture_count
    touch(session)
    return ok(public(session))


@bp.post("/scan-sessions/<session_id>/submit-acquisition")
@endpoint(TECHNOLOGIST)
def submit_acquisition(session_id):
    session = _session_for_acquisition(session_id)
    _require_session_technologist(session)
    rows = queries.measurements(session_id)
    if not rows:
        raise ApiError("ERR_NO_SITE_MEASUREMENTS",
                       "The session carries no site measurements.", 422)
    order = queries.order_of_session(session)
    measured_sites = {row["site_code"] for row in rows}
    if any(site not in measured_sites for site in order["requested_sites"]):
        raise ApiError("ERR_REQUESTED_SITES_INCOMPLETE",
                       "Every requested site must carry a measurement.", 422)
    if order["vfa_requested"] and not session["vfa_performed"]:
        raise ApiError("ERR_VFA_NOT_PERFORMED",
                       "The ordered vertebral fracture assessment has not been recorded.", 422)

    lowest_t, site, lowest_z = calc.diagnostic_selection(rows)
    session["submitted_at_utc"] = now_iso()
    session["lowest_t_score"] = lowest_t
    session["lowest_t_score_site"] = site
    session["lowest_z_score"] = lowest_z
    session["measured_site_count"] = len(rows)
    session["acquisition_status"] = "SUBMITTED"
    touch(session)

    appointment = db.scan_appointments.get(session["scan_appointment_id"])
    if appointment is not None and appointment["status"] == "CHECKED_IN":
        appointment["status"] = "COMPLETED"
        touch(appointment)
    if order["status"] == "SCHEDULED":
        order["status"] = "COMPLETED"
        touch(order)
        patient = db.patients.get(order["patient_id"])
        if patient is not None and patient["open_scheduled_order_count"] > 0:
            patient["open_scheduled_order_count"] -= 1
            touch(patient)
    return ok(public(session))


@bp.post("/scan-sessions/<session_id>/positioning-reviews")
@endpoint(QUALITY_REVIEWER, TECHNOLOGIST)
def create_positioning_review(session_id):
    body = validate.body()
    defect_codes = validate.enum_array(body, "defect_codes", DEFECT_CODES,
                                       non_empty=False)
    reviewer_note = validate.string(body, "reviewer_note", required=False, max_len=240)

    session = queries.session(session_id)
    if session["acquisition_status"] not in ("SUBMITTED", "ARCHIVED"):
        raise ApiError("ERR_SESSION_NOT_SUBMITTED", "The session is not SUBMITTED.")
    if session["review_status"] != "NOT_REVIEWED":
        raise ApiError("ERR_SESSION_ALREADY_REVIEWED",
                       "The session has already been reviewed.")
    if session["acquisition_status"] == "ARCHIVED":
        raise ApiError("ERR_SESSION_ARCHIVED", "The session is archived.")
    if actor_id() == session["technologist_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The acquiring technologist may not review their own study.", 403)

    severity, criterion_met, outcome = calc.positioning_outcome(
        defect_codes, session["repeat_count"])
    record = base_record(versioned=False)
    record.update({
        "scan_session_id": session_id,
        "reviewer_user_id": actor_id(),
        "reviewed_at_utc": now_iso(),
        "defect_codes": defect_codes,
        "reviewer_note": reviewer_note,
        "severity_score": severity,
        "repeat_criterion_met": criterion_met,
        "outcome": outcome,
    })
    db.positioning_reviews[record["id"]] = record
    session["review_status"] = outcome
    touch(session)
    return created(public(record))


@bp.get("/scan-sessions/<session_id>/positioning-reviews")
@endpoint(PROGRAM_ADMIN, TECHNOLOGIST, QUALITY_REVIEWER, INTERPRETING_PHYSICIAN)
def list_positioning_reviews(session_id):
    queries.session(session_id)
    rows = [row for row in db.positioning_reviews.values()
            if row["scan_session_id"] == session_id]
    rows.sort(key=lambda row: (row["reviewed_at_utc"], row["created_at"], row["_seq"]))
    return paginated(rows, public)


@bp.post("/scan-sessions/<session_id>/repeat-acquisition")
@endpoint(TECHNOLOGIST)
def repeat_acquisition(session_id):
    session = queries.session(session_id)
    if session["review_status"] not in ("REPEAT_REQUIRED", "ACCEPTED_WITH_LIMITATION"):
        raise ApiError("ERR_SESSION_REPEAT_NOT_REQUIRED",
                       "The session does not require a repeat.")
    if session["acquisition_status"] == "ARCHIVED":
        raise ApiError("ERR_SESSION_ARCHIVED", "The session is archived.")
    _require_session_technologist(session)
    if session["repeat_count"] >= calc.MAX_POSITIONING_REPEATS:
        raise ApiError("ERR_REPEAT_LIMIT_EXCEEDED",
                       "The session has already exhausted its permitted repeats.")

    for row in queries.measurements(session_id):
        row["superseded"] = True
    session["acquisition_status"] = "IN_PROGRESS"
    session["review_status"] = "NOT_REVIEWED"
    session["repeat_count"] += 1
    session["submitted_at_utc"] = None
    session["lowest_t_score"] = None
    session["lowest_t_score_site"] = None
    session["lowest_z_score"] = None
    session["measured_site_count"] = 0
    touch(session)
    return ok(public(session))
