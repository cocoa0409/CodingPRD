"""Intake assessments, eligibility screens and the determination endpoint."""

from flask import Blueprint, request

import db
from common import resolve_assessment, resolve_screen
from errors import ApiError
from response import (
    array_envelope,
    auth_context,
    body,
    object_envelope,
    page,
    pagination_args,
    require_role,
)
from services import eligibility, intake

bp = Blueprint("intake", __name__)


def _filter(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]


@bp.get("/intake-assessments")
def list_assessments():
    auth_context()
    require_role(_role(), ("IntakeSpecialist", "ComplianceOfficer"))
    limit, offset = pagination_args()
    matches = _filter(db.ordered("intake_assessments"), "client_id", request.args.get("client_id"))
    matches = _filter(matches, "status", request.args.get("status"))
    rows = [db.public(row) for row in page(matches, limit, offset)]
    return array_envelope(rows, limit, offset, len(matches))


@bp.get("/intake-assessments/<assessment_id>")
def read_assessment(assessment_id):
    auth_context()
    require_role(_role(), ("IntakeSpecialist", "ComplianceOfficer"))
    assessment = resolve_assessment(assessment_id)
    return object_envelope(db.public(assessment))


@bp.post("/intake-assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    auth_context()
    require_role(_role(), ("IntakeSpecialist",))
    assessment = resolve_assessment(assessment_id)
    intake.submit(assessment)
    return object_envelope(db.public(assessment))


@bp.post("/intake-assessments/<assessment_id>/route")
def route_assessment(assessment_id):
    auth_context()
    require_role(_role(), ("IntakeSpecialist",))
    assessment = resolve_assessment(assessment_id)
    intake.route(assessment)
    return object_envelope(db.public(assessment))


@bp.post("/intake-assessments/<assessment_id>/return")
def return_assessment(assessment_id):
    auth_context()
    require_role(_role(), ("ComplianceOfficer",))
    assessment = resolve_assessment(assessment_id)
    payload = body()
    intake.return_to_specialist(assessment, payload.get("return_reason_code"))
    return object_envelope(db.public(assessment))


@bp.post("/intake-assessments/<assessment_id>/eligibility-screens")
def open_screen(assessment_id):
    auth_context()
    require_role(_role(), ("IntakeSpecialist", "ComplianceOfficer"))
    assessment = resolve_assessment(assessment_id)
    screen = eligibility.create_screen(assessment, body())
    return object_envelope(db.public(screen)), 201


@bp.get("/eligibility-screens")
def list_screens():
    auth_context()
    require_role(_role(), ("IntakeSpecialist", "ProgramManager", "ComplianceOfficer"))
    limit, offset = pagination_args()
    matches = _filter(db.ordered("eligibility_screens"), "intake_assessment_id",
                      request.args.get("intake_assessment_id"))
    matches = _filter(matches, "program_id", request.args.get("program_id"))
    matches = _filter(matches, "grant_id", request.args.get("grant_id"))
    matches = _filter(matches, "determination", request.args.get("determination"))
    rows = [db.public(row) for row in page(matches, limit, offset)]
    return array_envelope(rows, limit, offset, len(matches))


@bp.get("/eligibility-screens/<screen_id>")
def read_screen(screen_id):
    auth_context()
    require_role(_role(), ("IntakeSpecialist", "ProgramManager", "ComplianceOfficer"))
    screen = resolve_screen(screen_id)
    return object_envelope(db.public(screen))


@bp.post("/eligibility-screens/<screen_id>/determine")
def determine_screen(screen_id):
    auth_context()
    require_role(_role(), ("ComplianceOfficer",))
    screen = resolve_screen(screen_id)
    eligibility.determine(screen, body())
    return object_envelope(db.public(screen))


def _role():
    return request.headers.get("X-User-Role")
