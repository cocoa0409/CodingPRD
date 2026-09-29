"""Patients: registration, eligibility review and status actions (PRD 3.3)."""
from flask import Blueprint

import constants
import db
import response
import validate
from errors import ERR_INVALID_PATIENT_STATE, fail
from middleware import endpoint
from routes.common import page
from services import lookup, patients as patient_svc
from validate import Field

bp = Blueprint("patients", __name__)

PATIENT_READ_ROLES = ("ProgramAdmin", "LogisticsCoordinator", "IntakeTechnician", "Patient")
PATIENT_LIST_ROLES = ("ProgramAdmin", "LogisticsCoordinator", "IntakeTechnician")

PATIENT_SCHEMA = [
    Field("full_name", "string", required=True, min_len=1),
    Field("state_rule_id", "string", required=True, min_len=1),
    Field("therapy_type", "enum", required=True, values=constants.THERAPY_TYPES),
    Field("weekly_sharps_count", "int", required=True, minimum=1, maximum=500),
    Field("contact_email", "string", required=True, min_len=1),
]

REVIEW_SCHEMA = [
    Field("decision", "enum", required=True, values=["APPROVE", "DENY"]),
    Field("note", "string"),
]

STATUS_ACTION_SCHEMA = [
    Field("action", "enum", required=True, values=["SUSPEND", "REINSTATE", "WITHDRAW"]),
    Field("reason", "string"),
]

WITHDRAWABLE_PATIENT_STATUSES = ("ELIGIBLE", "ENROLLED", "SUSPENDED")


@bp.post("/sharps/patients")
@endpoint(["ProgramAdmin"])
def create_patient():
    body, _provided = validate.parse_body(PATIENT_SCHEMA)
    lookup.require("state_rule", body["state_rule_id"])
    row = db.create_row(
        "patients",
        {
            "full_name": body["full_name"],
            "state_rule_id": body["state_rule_id"],
            "therapy_type": body["therapy_type"],
            "weekly_sharps_count": body["weekly_sharps_count"],
            "contact_email": body["contact_email"],
            "screening_risk_score": 0,
            "audit_risk_score": 0,
            "suspended_at": None,
            "status": "PENDING_ELIGIBILITY",
        },
    )
    return response.created(response.view("patient", row))


@bp.post("/sharps/patients/<patient_id>/eligibility-review")
@endpoint(["ProgramAdmin"])
def eligibility_review(patient_id):
    body, _provided = validate.parse_body(REVIEW_SCHEMA)
    patient = lookup.require("patient", patient_id)
    if patient["status"] != "PENDING_ELIGIBILITY":
        fail(ERR_INVALID_PATIENT_STATE)
    patient["status"] = "ELIGIBLE" if body["decision"] == "APPROVE" else "INELIGIBLE"
    db.bump(patient)
    return response.ok(response.view("patient", patient))


@bp.post("/sharps/patients/<patient_id>/status-actions")
@endpoint(["ProgramAdmin"])
def patient_status_action(patient_id):
    body, _provided = validate.parse_body(STATUS_ACTION_SCHEMA)
    patient = lookup.require("patient", patient_id)
    action = body["action"]
    if action == "SUSPEND":
        if patient["status"] != "ENROLLED":
            fail(ERR_INVALID_PATIENT_STATE)
        patient_svc.suspend_patient(patient)
    elif action == "REINSTATE":
        if patient["status"] != "SUSPENDED":
            fail(ERR_INVALID_PATIENT_STATE)
        patient_svc.reinstate_patient(patient)
    else:
        if patient["status"] not in WITHDRAWABLE_PATIENT_STATUSES:
            fail(ERR_INVALID_PATIENT_STATE)
        patient_svc.withdraw_patient(patient)
    return response.ok(response.view("patient", patient))


@bp.get("/sharps/patients/<patient_id>")
@endpoint(PATIENT_READ_ROLES, mutating=False)
def get_patient(patient_id):
    row = lookup.require("patient", patient_id)
    return response.ok(response.view("patient", row))


@bp.get("/sharps/patients")
@endpoint(PATIENT_LIST_ROLES, mutating=False)
def list_patients():
    limit, offset = validate.pagination()
    state_rule_id = validate.qs_str("state_rule_id")
    status = validate.qs_enum("status", constants.PATIENT_STATUSES)
    lookup.require_filter("state_rule", state_rule_id)
    rows = db.ordered("patients")
    if state_rule_id is not None:
        rows = [r for r in rows if r["state_rule_id"] == state_rule_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("patient", rows, limit, offset)
