"""Survivorship study, enrollment and follow-up endpoints (PRD §3.8)."""

from datetime import timedelta

from flask import Blueprint

from db import DB, add_months, add_years, clock, new_row, now_iso, parse_iso, touch
from errors import ApiError
from http_util import body_json, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    get_or_404, serialize_follow_up, serialize_study,
    serialize_survivorship_enrollment,
)

bp = Blueprint("survivorship", __name__)


@bp.post("/programs/clinical-protocols/<protocol_id>/studies")
def create_study(protocol_id):
    require_role("SurvivorshipCoordinator")
    protocol = get_or_404("protocols", protocol_id)
    data = body_json()
    study_code = required(data, "study_code", "str")
    interval = required(data, "follow_up_interval_months", "int")
    if interval <= 0:
        raise ApiError("ERR_INVALID_REQUEST")
    min_years = required(data, "min_years_after_completion", "int")
    if min_years <= 0:
        raise ApiError("ERR_INVALID_REQUEST")

    for existing in DB["studies"].values():
        if (existing["protocol_id"] == protocol_id
                and existing["study_code"] == study_code):
            raise ApiError("ERR_DUPLICATE_ENTITY")

    study = new_row({
        "protocol_id": protocol_id,
        "study_code": study_code,
        "follow_up_interval_months": interval,
        "min_years_after_completion": min_years,
        "status": "ACTIVE",
    })
    DB["studies"][study["id"]] = study
    return success_object(serialize_study(study), 201)


@bp.get("/programs/survivorship-studies")
def list_studies():
    require_role("Any")
    protocol_id = arg("protocol_id")
    status = arg("status")
    rows = ordered(DB["studies"].values())
    rows = filtered(rows, protocol_id=protocol_id, status=status)
    return list_response(rows, serialize_study)


@bp.post("/programs/survivorship-studies/<study_id>/enrollments")
def create_survivorship_enrollment(study_id):
    require_role("SurvivorshipCoordinator")
    study = get_or_404("studies", study_id)
    data = body_json()
    enrollment_id = required(data, "enrollment_id", "str")
    enrollment = get_or_404("enrollments", enrollment_id)
    completed_treatment_at = required(data, "completed_treatment_at", "datetime")

    if study["status"] != "ACTIVE":
        raise ApiError("ERR_STUDY_NOT_ACTIVE")

    row = new_row({
        "study_id": study["id"],
        "enrollment_id": enrollment["id"],
        "completed_treatment_at": completed_treatment_at,
        "adult_transition_age_years": 18,
        "next_due_at": completed_treatment_at,
        "is_adult_follow_up": False,
        "status": "ON_STUDY",
    })
    DB["survivorship_enrollments"][row["id"]] = row
    return success_object(serialize_survivorship_enrollment(row), 201)


@bp.get("/programs/survivorship-studies/<study_id>/enrollments")
def list_study_enrollments(study_id):
    require_role("Any")
    get_or_404("studies", study_id)
    status = arg("status")
    rows = ordered([s for s in DB["survivorship_enrollments"].values()
                    if s["study_id"] == study_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_survivorship_enrollment)


@bp.get("/programs/survivorship-enrollments")
def list_survivorship_enrollments():
    require_role("Any")
    rows = ordered(DB["survivorship_enrollments"].values())
    rows = filtered(rows, study_id=arg("study_id"),
                    enrollment_id=arg("enrollment_id"), status=arg("status"))
    return list_response(rows, serialize_survivorship_enrollment)


@bp.get("/programs/survivorship-enrollments/<survivorship_enrollment_id>")
def get_survivorship_enrollment(survivorship_enrollment_id):
    require_role("Any")
    row = get_or_404("survivorship_enrollments", survivorship_enrollment_id)
    return success_object(serialize_survivorship_enrollment(row), 200)


def _visits(row):
    visits = [v for v in DB["follow_ups"].values()
              if v["survivorship_enrollment_id"] == row["id"]]
    visits.sort(key=lambda v: (v["completed_at"], v["created_at"]))
    return visits


@bp.post("/programs/survivorship-enrollments/<survivorship_enrollment_id>/follow-ups")
def log_follow_up(survivorship_enrollment_id):
    require_role("SurvivorshipCoordinator")
    row = get_or_404("survivorship_enrollments", survivorship_enrollment_id)
    study = get_or_404("studies", row["study_id"])
    data = body_json()
    completed_at = required(data, "completed_at", "datetime")

    if row["status"] != "ON_STUDY":
        raise ApiError("ERR_SURVIVORSHIP_NOT_ON_STUDY")
    if study["status"] != "ACTIVE":
        raise ApiError("ERR_STUDY_NOT_ACTIVE")

    visits = _visits(row)
    if visits and parse_iso(completed_at) < parse_iso(visits[-1]["completed_at"]):
        raise ApiError("ERR_FOLLOW_UP_WINDOW_VIOLATION")
    if visits:
        base = parse_iso(row["completed_treatment_at"])
        expected_instant = add_months(
            base, (len(visits) + 1) * int(study["follow_up_interval_months"]))
        if parse_iso(completed_at) < expected_instant:
            raise ApiError("ERR_FOLLOW_UP_WINDOW_VIOLATION")
    else:
        base = parse_iso(row["completed_treatment_at"])
        first_due = add_months(base, int(study["follow_up_interval_months"]))
        if parse_iso(completed_at) < first_due:
            raise ApiError("ERR_FOLLOW_UP_WINDOW_VIOLATION")

    follow_up = new_row({
        "survivorship_enrollment_id": row["id"],
        "completed_at": completed_at,
        "status": "LOGGED",
    })
    DB["follow_ups"][follow_up["id"]] = follow_up

    visits = _visits(row)
    terminal = add_months(parse_iso(row["completed_treatment_at"]),
                          int(study["min_years_after_completion"]) * 12)
    if clock() >= terminal and parse_iso(completed_at) >= terminal:
        row["status"] = "GRADUATED"
        touch(row)
    return success_object(serialize_follow_up(follow_up), 200)


@bp.get("/programs/survivorship-enrollments/<survivorship_enrollment_id>/follow-ups")
def list_follow_ups(survivorship_enrollment_id):
    require_role("Any")
    get_or_404("survivorship_enrollments", survivorship_enrollment_id)
    status = arg("status")
    rows = _visits(DB["survivorship_enrollments"][survivorship_enrollment_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_follow_up)


@bp.post("/programs/survivorship-enrollments/<survivorship_enrollment_id>/withdraw")
def withdraw_survivorship_enrollment(survivorship_enrollment_id):
    require_role("SurvivorshipCoordinator")
    row = get_or_404("survivorship_enrollments", survivorship_enrollment_id)
    body_json()
    if row["status"] != "ON_STUDY":
        raise ApiError("ERR_SURVIVORSHIP_NOT_ON_STUDY")
    row["status"] = "WITHDRAWN"
    touch(row)
    return success_object(serialize_survivorship_enrollment(row), 200)