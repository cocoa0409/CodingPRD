"""Enrollments and operator kit issuance (PRD 3.3, 3.4)."""
from flask import Blueprint

import clock
import constants
import db
import middleware
import response
import validate
from errors import (
    ERR_DUPLICATE_ACTIVE_ENROLLMENT,
    ERR_INVALID_ENROLLMENT_STATE,
    ERR_INVALID_PATIENT_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PROGRAM_FUNDING_EXHAUSTED,
    ERR_SPONSOR_NOT_ACTIVE,
    ERR_STALE_ENROLLMENT_VERSION,
    fail,
)
from middleware import endpoint
from routes.common import page
from services import kits as kit_svc
from services import lookup
from validate import Field

bp = Blueprint("enrollments", __name__)

ENROLLMENT_READ_ROLES = (
    "ProgramAdmin",
    "LogisticsCoordinator",
    "SponsorRepresentative",
    "Patient",
)
ENROLLMENT_LIST_ROLES = ("ProgramAdmin", "LogisticsCoordinator", "SponsorRepresentative")
KIT_READ_ROLES = (
    "ProgramAdmin",
    "LogisticsCoordinator",
    "IntakeTechnician",
    "DestructionOfficer",
    "Patient",
)
KIT_LIST_ROLES = ("ProgramAdmin", "LogisticsCoordinator", "IntakeTechnician", "DestructionOfficer")

LIVE_ENROLLMENT_STATUSES = ("DRAFT", "PENDING_SPONSOR_APPROVAL", "ACTIVE", "PAUSED")

ENROLLMENT_SCHEMA = [
    Field("patient_id", "string", required=True, min_len=1),
    Field("sponsorship_program_id", "string", required=True, min_len=1),
    Field("cadence_days", "int", required=True, minimum=14, maximum=180),
    Field("kits_authorized", "int", required=True, minimum=1, maximum=24),
    Field("requested_container_size", "enum", default=None, values=constants.CONTAINER_SIZES),
]

DECISION_SCHEMA = [
    Field("decision", "enum", required=True, values=["APPROVE", "REJECT"]),
    Field("sponsor_decision_note", "string"),
]

KIT_ISSUE_SCHEMA = [
    Field("expected_enrollment_version", "int", required=True),
    Field("container_size", "enum", default=None, values=constants.CONTAINER_SIZES),
]


@bp.post("/sharps/enrollments")
@endpoint(["ProgramAdmin"])
def create_enrollment():
    body, _provided = validate.parse_body(ENROLLMENT_SCHEMA)
    patient = lookup.require("patient", body["patient_id"])
    program = lookup.require("program", body["sponsorship_program_id"])
    if patient["status"] not in ("ELIGIBLE", "ENROLLED"):
        fail(ERR_INVALID_PATIENT_STATE)
    sponsor = lookup.program_sponsor(program)
    if sponsor is None or sponsor["status"] != "ACTIVE":
        fail(ERR_SPONSOR_NOT_ACTIVE)
    for existing in lookup.patient_enrollments(patient["id"]):
        if (
            existing["sponsorship_program_id"] == program["id"]
            and existing["status"] in LIVE_ENROLLMENT_STATUSES
        ):
            fail(ERR_DUPLICATE_ACTIVE_ENROLLMENT)
    row = db.create_row(
        "enrollments",
        {
            "patient_id": patient["id"],
            "sponsorship_program_id": program["id"],
            "cadence_days": body["cadence_days"],
            "kits_authorized": body["kits_authorized"],
            "requested_container_size": body["requested_container_size"],
            "kits_issued": 0,
            "next_autoship_due_date": None,
            "activated_at": None,
            "sponsor_decision_note": None,
            "status": "DRAFT",
        },
    )
    return response.created(response.view("enrollment", row))


@bp.post("/sharps/enrollments/<enrollment_id>/submit")
@endpoint(["ProgramAdmin"])
def submit_enrollment(enrollment_id):
    validate.parse_body([])
    enrollment = lookup.require("enrollment", enrollment_id)
    if enrollment["status"] != "DRAFT":
        fail(ERR_INVALID_ENROLLMENT_STATE)
    patient = lookup.enrollment_patient(enrollment)
    if patient is None or patient["status"] not in ("ELIGIBLE", "ENROLLED"):
        fail(ERR_INVALID_PATIENT_STATE)
    program = lookup.enrollment_program(enrollment)
    sponsor = lookup.program_sponsor(program) if program is not None else None
    if sponsor is None or sponsor["status"] != "ACTIVE":
        fail(ERR_SPONSOR_NOT_ACTIVE)
    enrollment["status"] = "PENDING_SPONSOR_APPROVAL"
    db.bump(enrollment)
    return response.ok(response.view("enrollment", enrollment))


@bp.post("/sharps/enrollments/<enrollment_id>/sponsor-decision")
@endpoint(["SponsorRepresentative"])
def sponsor_decision(enrollment_id):
    body, _provided = validate.parse_body(DECISION_SCHEMA)
    enrollment = lookup.require("enrollment", enrollment_id)
    program = lookup.enrollment_program(enrollment)
    if program is None or middleware.user_id() != program["sponsor_id"]:
        fail(ERR_NOT_RESOURCE_OWNER)
    if enrollment["status"] != "PENDING_SPONSOR_APPROVAL":
        fail(ERR_INVALID_ENROLLMENT_STATE)

    if body["decision"] == "APPROVE":
        sponsor = lookup.program_sponsor(program)
        if sponsor is None or sponsor["status"] != "ACTIVE":
            fail(ERR_SPONSOR_NOT_ACTIVE)
        if program["status"] != "ACTIVE":
            fail(ERR_PROGRAM_FUNDING_EXHAUSTED)
        enrollment["status"] = "ACTIVE"
        enrollment["activated_at"] = clock.now_iso()
        enrollment["sponsor_decision_note"] = body["sponsor_decision_note"]
        enrollment["next_autoship_due_date"] = clock.now_date_iso()
        patient = lookup.enrollment_patient(enrollment)
        if patient is not None and patient["status"] == "ELIGIBLE":
            patient["status"] = "ENROLLED"
            db.bump(patient)
    else:
        enrollment["status"] = "REJECTED"
        enrollment["sponsor_decision_note"] = body["sponsor_decision_note"]
    db.bump(enrollment)
    return response.ok(response.view("enrollment", enrollment))


@bp.get("/sharps/enrollments/<enrollment_id>")
@endpoint(ENROLLMENT_READ_ROLES, mutating=False)
def get_enrollment(enrollment_id):
    row = lookup.require("enrollment", enrollment_id)
    return response.ok(response.view("enrollment", row))


@bp.get("/sharps/enrollments")
@endpoint(ENROLLMENT_LIST_ROLES, mutating=False)
def list_enrollments():
    limit, offset = validate.pagination()
    patient_id = validate.qs_str("patient_id")
    program_id = validate.qs_str("sponsorship_program_id")
    status = validate.qs_enum("status", constants.ENROLLMENT_STATUSES)
    lookup.require_filter("patient", patient_id)
    lookup.require_filter("program", program_id)
    rows = db.ordered("enrollments")
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if program_id is not None:
        rows = [r for r in rows if r["sponsorship_program_id"] == program_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("enrollment", rows, limit, offset)


# ---- kit issuance -------------------------------------------------------

@bp.post("/sharps/enrollments/<enrollment_id>/kits")
@endpoint(["ProgramAdmin", "LogisticsCoordinator"])
def issue_kit(enrollment_id):
    body, provided = validate.parse_body(KIT_ISSUE_SCHEMA)
    enrollment = lookup.require("enrollment", enrollment_id)
    if enrollment["status"] != "ACTIVE":
        fail(ERR_INVALID_ENROLLMENT_STATE)
    patient = lookup.enrollment_patient(enrollment)
    if patient is None or patient["status"] != "ENROLLED":
        fail(ERR_INVALID_PATIENT_STATE)
    if body["expected_enrollment_version"] != enrollment["version"]:
        fail(ERR_STALE_ENROLLMENT_VERSION)

    program = lookup.enrollment_program(enrollment)
    state_rule = lookup.patient_state_rule(patient)
    requested = body["container_size"]
    if requested is None:
        requested = enrollment["requested_container_size"]
    plan = kit_svc.plan_kit(enrollment, patient, state_rule, requested)
    kit = kit_svc.issue_kit(enrollment, program, plan, clock.now_date())
    return response.created(response.view("kit", kit))


@bp.get("/sharps/kits/<kit_id>")
@endpoint(KIT_READ_ROLES, mutating=False)
def get_kit(kit_id):
    row = lookup.require("kit", kit_id)
    return response.ok(response.view("kit", row))


@bp.get("/sharps/kits")
@endpoint(KIT_LIST_ROLES, mutating=False)
def list_kits():
    limit, offset = validate.pagination()
    enrollment_id = validate.qs_str("enrollment_id")
    supersedes_kit_id = validate.qs_str("supersedes_kit_id")
    auto_ship_run_id = validate.qs_str("auto_ship_run_id")
    status = validate.qs_enum("status", constants.KIT_STATUSES)
    lookup.require_filter("enrollment", enrollment_id)
    lookup.require_filter("kit", supersedes_kit_id)
    lookup.require_filter("autoship_run", auto_ship_run_id)
    rows = db.ordered("kits")
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if supersedes_kit_id is not None:
        rows = [r for r in rows if r["supersedes_kit_id"] == supersedes_kit_id]
    if auto_ship_run_id is not None:
        rows = [r for r in rows if r["auto_ship_run_id"] == auto_ship_run_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("kit", rows, limit, offset)
