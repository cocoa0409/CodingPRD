"""Certification standards."""
import re

from flask import Blueprint, request

import serial
from core import base_row, store
from routes.common import created, listing, ok, path_row, require_roles, unique_or_conflict
from validate import body, opt_int, req_decimal, req_int, req_str, topic_requirements

bp = Blueprint("standards", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

READ_ONE_ROLES = (
    "AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
    "BackgroundInvestigator", "MedicalExaminer", "AcademyInstructor",
    "FieldTrainingOfficer",
)
LIST_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian", "AcademyInstructor")


@bp.post("/certification-standards")
def create_standard():
    require_roles("AcademyDirector")
    payload = body()
    code = req_str(payload, "code", min_len=1, max_len=40)
    state_code = req_str(payload, "state_code", min_len=2, max_len=2)
    if not STATE_CODE_RE.match(state_code):
        from core import fail
        fail("ERR_INVALID_REQUEST", "state_code must be two uppercase letters")
    min_total_hours = req_decimal(payload, "min_total_hours", minimum=0, exclusive_min=True)
    min_passing_score = req_decimal(payload, "min_passing_score", minimum=0, maximum=100,
                                    exclusive_min=True)
    max_remediation_attempts = req_int(payload, "max_remediation_attempts", minimum=0)
    max_absence_hours = req_decimal(payload, "max_absence_hours", minimum=0)
    topics = topic_requirements(payload)
    floor_points = opt_int(payload, "fitness_event_floor_points", minimum=0, maximum=25,
                           default=10)
    pass_score = opt_int(payload, "fitness_pass_score", minimum=0, maximum=100, default=60)

    unique_or_conflict("standards", "code", code)

    row = base_row()
    row.update({
        "code": code,
        "state_code": state_code,
        "min_total_hours": min_total_hours,
        "min_passing_score": min_passing_score,
        "max_remediation_attempts": max_remediation_attempts,
        "max_absence_hours": max_absence_hours,
        "topic_requirements": topics,
        "fitness_event_floor_points": floor_points,
        "fitness_pass_score": pass_score,
    })
    store.standards[row["id"]] = row
    return created(serial.standard_json(row))


@bp.get("/certification-standards/<standard_id>")
def read_standard(standard_id):
    require_roles(*READ_ONE_ROLES)
    row = path_row("standards", standard_id)
    return ok(serial.standard_json(row))


@bp.get("/certification-standards")
def list_standards():
    require_roles(*LIST_ROLES)
    state_code = request.args.get("state_code")

    def predicate(row):
        return state_code is None or row["state_code"] == state_code

    return listing("standards", serial.standard_json, predicate)
