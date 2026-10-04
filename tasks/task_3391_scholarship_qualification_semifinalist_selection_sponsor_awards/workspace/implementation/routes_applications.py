"""Finalist application endpoints: create, read, list, endorse, submit,
review (OCC-guarded, three decisions)."""

from flask import Blueprint, g, request

import constants as C
from errors import err
from helpers import (
    apply_filters,
    bad,
    body,
    check_enum_field,
    check_int_field,
    check_num_field,
    created_key,
    is_int,
    paginate,
    require_present,
    require_roles,
    resp_object,
)
from serializers import ser_application
from store import base_record, clock_now, db, iso_z, parse_dt, touch

bp = Blueprint("applications", __name__)


def _get_application_or_404(application_id):
    rec = db["applications"].get(application_id)
    if rec is None:
        err("ERR_NOT_FOUND", "finalist application not found")
    return rec


def _cycle_of(app):
    return db["cycles"][db["entries"][app["entry_id"]]["cycle_id"]]


@bp.route("/api/finalist-applications", methods=["POST"])
@require_roles(C.ROLE_STUDENT)
def create_application():
    b = body()
    # Priority 4, body-referenced ids must exist (entry_id,
    # first_choice_college_id). Ownership needs the entry, so entry
    # resolution necessarily precedes it here.
    if b.get("entry_id") is not None and b["entry_id"] not in db["entries"]:
        bad("referenced entry_id does not exist")
    if b.get("first_choice_college_id") is not None and b["first_choice_college_id"] not in db["colleges"]:
        bad("referenced first_choice_college_id does not exist")
    require_present(b, "entry_id")
    entry = db["entries"][b["entry_id"]]
    # Priority 3, ownership: X-User-ID equal to the entry's student.
    if g.user_id != entry["student_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "students may only apply for their own entries")
    cycle = db["cycles"][entry["cycle_id"]]
    # Priority 6, posture gate.
    if cycle["status"] != "SEMIFINALISTS_SELECTED":
        err("ERR_CYCLE_POSTURE_INVALID", "applications require SEMIFINALISTS_SELECTED posture")
    # Priority 7, semifinalist standing before the duplicate-application check.
    if entry["status"] != "SELECTED_SEMIFINALIST":
        err("ERR_ENTRY_NOT_SEMIFINALIST", "entry is not SELECTED_SEMIFINALIST")
    for app in db["applications"].values():
        if app["entry_id"] == entry["id"]:
            bad("an application already exists for this entry")
    # Priority 8, application window (logical clock at or before deadline).
    if clock_now() > parse_dt(cycle["application_deadline"]):
        err("ERR_APPLICATION_WINDOW_CLOSED", "application deadline has passed")
    # Priority 10, field shape.
    require_present(b, "gpa_scaled", "course_rigor", "confirming_selection_index")
    check_num_field(b, "gpa_scaled", minimum=C.GPA_MIN, maximum=C.GPA_MAX)
    check_enum_field(b, "course_rigor", C.COURSE_RIGORS)
    check_int_field(
        b, "confirming_selection_index", minimum=C.CONFIRMING_MIN, maximum=C.CONFIRMING_MAX
    )
    rec = base_record()
    rec.update(
        {
            "entry_id": entry["id"],
            "student_id": entry["student_id"],
            "first_choice_college_id": b.get("first_choice_college_id"),
            "gpa_scaled": b["gpa_scaled"],
            "course_rigor": b["course_rigor"],
            "confirming_selection_index": b["confirming_selection_index"],
            "endorsement_status": "PENDING",
            "endorsed_by_school_id": None,
            "status": "IN_PROGRESS",
            "return_reason": None,
            "submitted_at": None,
        }
    )
    db["applications"][rec["id"]] = rec
    return resp_object(ser_application(rec), code=201)


@bp.route("/api/finalist-applications/<application_id>", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_STUDENT, C.ROLE_SCHOOL_OFFICIAL)
def get_application(application_id):
    rec = _get_application_or_404(application_id)
    if g.user_role == C.ROLE_STUDENT and g.user_id != rec["student_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "students may only read their own applications")
    return resp_object(ser_application(rec))


@bp.route("/api/finalist-applications", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_SCHOOL_OFFICIAL, C.ROLE_COLLEGE_ADMIN)
def list_applications():
    records = sorted(db["applications"].values(), key=created_key)
    records = apply_filters(
        records,
        [
            ("entry_id", request.args.get("entry_id")),
            ("student_id", request.args.get("student_id")),
            ("first_choice_college_id", request.args.get("first_choice_college_id")),
            ("endorsed_by_school_id", request.args.get("endorsed_by_school_id")),
            ("status", request.args.get("status")),
        ],
    )
    return paginate(records, ser_application)


@bp.route("/api/finalist-applications/<application_id>/endorse", methods=["POST"])
@require_roles(C.ROLE_SCHOOL_OFFICIAL)
def endorse_application(application_id):
    rec = _get_application_or_404(application_id)
    # Priority 3, school ownership: the student's school_id == X-User-ID.
    student = db["students"][rec["student_id"]]
    if student["school_id"] != g.user_id:
        err("ERR_ENDORSEMENT_SCHOOL_MISMATCH", "official may only endorse their own school's students")
    # Priority 6: endorsement is pinned to pre-submission IN_PROGRESS and
    # fires exactly once (an endorsed-but-unsubmitted application rejects a
    # repeat endorsement with ERR_INVALID_STATE).
    if rec["status"] != "IN_PROGRESS" or rec["endorsement_status"] != "PENDING":
        err("ERR_INVALID_STATE", "application is not endorsable")
    rec["endorsement_status"] = "ENDORSED"
    rec["endorsed_by_school_id"] = g.user_id
    touch(rec)
    return resp_object(ser_application(rec))


@bp.route("/api/finalist-applications/<application_id>/submit", methods=["POST"])
@require_roles(C.ROLE_STUDENT)
def submit_application(application_id):
    rec = _get_application_or_404(application_id)
    # Priority 3, ownership.
    if g.user_id != rec["student_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "students may only submit their own applications")
    cycle = _cycle_of(rec)
    # Priority 6, posture gate.
    if cycle["status"] != "SEMIFINALISTS_SELECTED":
        err("ERR_CYCLE_POSTURE_INVALID", "submit requires SEMIFINALISTS_SELECTED posture")
    # Priority 6, entity state: IN_PROGRESS or RETURNED_FOR_CORRECTION.
    if rec["status"] not in ("IN_PROGRESS", "RETURNED_FOR_CORRECTION"):
        err("ERR_INVALID_STATE", "application is not submittable")
    # Priority 7, finalist requirements.
    if rec["endorsement_status"] != "ENDORSED":
        err("ERR_APPLICATION_INCOMPLETE", "application lacks a school endorsement")
    if rec["confirming_selection_index"] < cycle["confirming_floor"]:
        err("ERR_CONFIRMING_SCORE_BELOW_FLOOR", "confirming selection index below the floor")
    # Priority 8, application window.
    if clock_now() > parse_dt(cycle["application_deadline"]):
        err("ERR_APPLICATION_WINDOW_CLOSED", "application deadline has passed")
    rec["status"] = "UNDER_REVIEW"
    rec["submitted_at"] = iso_z(clock_now())
    rec["return_reason"] = None
    touch(rec)
    return resp_object(ser_application(rec))


@bp.route("/api/finalist-applications/<application_id>/review", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def review_application(application_id):
    rec = _get_application_or_404(application_id)
    b = body()
    decision = b.get("decision")
    cycle = _cycle_of(rec)
    # Priority 5, optimistic concurrency.
    if "expected_finalist_application_version" in b and b["expected_finalist_application_version"] is not None:
        if b["expected_finalist_application_version"] != rec["version"]:
            err("ERR_STALE_VERSION", "application version has advanced")
    # Priority 6, posture gate (CONFIRM additionally requires the posture).
    if decision == "CONFIRM" and cycle["status"] != "SEMIFINALISTS_SELECTED":
        err("ERR_CYCLE_POSTURE_INVALID", "confirm requires SEMIFINALISTS_SELECTED posture")
    # Priority 6, entity state: only UNDER_REVIEW applications may be reviewed.
    if rec["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", "application is not UNDER_REVIEW")
    if decision not in C.REVIEW_DECISIONS:
        bad("decision must be one of CONFIRM, RETURN, DENY")
    if decision == "CONFIRM":
        # Priority 7, finalist requirements.
        if rec["endorsement_status"] != "ENDORSED":
            err("ERR_APPLICATION_INCOMPLETE", "application lacks a school endorsement")
        if rec["confirming_selection_index"] < cycle["confirming_floor"]:
            err("ERR_CONFIRMING_SCORE_BELOW_FLOOR", "confirming selection index below the floor")
    elif decision == "RETURN":
        if not b.get("return_reason") or not isinstance(b.get("return_reason"), str):
            bad("return_reason must be a non-empty string for RETURN")
    # Priority 10: the OCC version field is required on this endpoint.
    if "expected_finalist_application_version" not in b or b["expected_finalist_application_version"] is None:
        bad("expected_finalist_application_version is required")
    # All gates passed; apply the transition.
    if decision == "CONFIRM":
        rec["status"] = "FINALIST_CONFIRMED"
    elif decision == "RETURN":
        rec["status"] = "RETURNED_FOR_CORRECTION"
        rec["return_reason"] = b["return_reason"]
    else:  # DENY
        rec["status"] = "DENIED"
    touch(rec)
    return resp_object(ser_application(rec))
