"""PRD 3.9 — manufacturer warranty registration, decision and reopening."""

from flask import Blueprint, request

import calc
import lookup
import rollups
import serial
from auth import (CERTIFIER, CLIENT, DESIGN_ENGINEER, MANUFACTURER_AGENT,
                  PROJECT_MANAGER, require)
from envelope import created, enum_filter, ok, paginate
from errors import ApiError
from store import base_record, db, touch
from validation import Field, body, no_body

warranty_bp = Blueprint("warranty", __name__)

MANUFACTURER_PROGRAMS = ("STANDARD_15Y", "EXTENDED_25Y")
REGISTRATION_STATES = ("DRAFT", "READY", "SUBMITTED", "REGISTERED", "REJECTED",
                       "REVOKED")
DECISIONS = ("REGISTER", "REJECT")
READ_ROLES = (PROJECT_MANAGER, DESIGN_ENGINEER, CERTIFIER, MANUFACTURER_AGENT, CLIENT)


@warranty_bp.route("/cabling/warranty-registrations", methods=["POST"])
@require(PROJECT_MANAGER)
def open_registration():
    values = body([
        Field("project_id", "string"),
        Field("manufacturer_program", "enum", enum=MANUFACTURER_PROGRAMS),
    ])
    project = lookup.project(values["project_id"])
    registration = base_record()
    registration.update({
        "project_id": project["id"],
        "manufacturer_program": values["manufacturer_program"],
        "registration_state": "DRAFT",
        "pinned_project_version": None,
        "submitted_certified_link_count": None,
        "coverage_years": None,
        "registration_number": None,
        "rejection_reason": None,
    })
    db.registrations[registration["id"]] = registration
    return created(serial.public(registration))


@warranty_bp.route("/cabling/warranty-registrations/<registration_id>", methods=["GET"])
@require(*READ_ROLES)
def read_registration(registration_id):
    return ok(serial.public(lookup.registration(registration_id)))


@warranty_bp.route("/cabling/warranty-registrations", methods=["GET"])
@require(*READ_ROLES)
def list_registrations():
    project_id = request.args.get("project_id")
    registration_state = enum_filter(request.args, "registration_state",
                                     REGISTRATION_STATES)
    manufacturer_program = enum_filter(request.args, "manufacturer_program",
                                       MANUFACTURER_PROGRAMS)
    rows = []
    for registration in db.registrations.values():
        if project_id is not None and registration["project_id"] != project_id:
            continue
        if (registration_state is not None
                and registration["registration_state"] != registration_state):
            continue
        if (manufacturer_program is not None
                and registration["manufacturer_program"] != manufacturer_program):
            continue
        rows.append(registration)
    return paginate(rows, request.args, serial.public)


@warranty_bp.route("/cabling/warranty-registrations/<registration_id>/submit",
                   methods=["POST"])
@require(PROJECT_MANAGER)
def submit_registration(registration_id):
    values = body([Field("expected_project_version", "integer")])
    registration = lookup.registration(registration_id)
    project = db.projects.get(registration["project_id"])
    if registration["registration_state"] != "READY":
        raise ApiError("ERR_INVALID_WARRANTY_STATE",
                       "Only a READY registration can be submitted.")
    if project is None or values["expected_project_version"] != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION",
                       "expected_project_version does not match the project's version.")
    if project["warranty_status"] != "ELIGIBLE":
        raise ApiError("ERR_WARRANTY_NOT_ELIGIBLE",
                       "The project's warranty_status must be ELIGIBLE.")
    rework_links = len([l for l in rollups.project_links(project["id"])
                        if l["test_attempt_count"] >= calc.WARRANTY_REWORK_ATTEMPT_THRESHOLD])
    registration["registration_state"] = "SUBMITTED"
    registration["submitted_certified_link_count"] = project["certified_link_count"]
    registration["coverage_years"] = calc.coverage_years(
        registration["manufacturer_program"], rework_links)
    project["warranty_status"] = "SUBMITTED"
    touch(project)
    # The pin always names the project revision the manufacturer will decide on.
    registration["pinned_project_version"] = project["version"]
    touch(registration)
    return ok(serial.public(registration))


@warranty_bp.route("/cabling/warranty-registrations/<registration_id>/decision",
                   methods=["POST"])
@require(MANUFACTURER_AGENT)
def decide_registration(registration_id):
    values = body([
        Field("decision", "enum", enum=DECISIONS),
        Field("registration_number", "string", required=False, default=None),
        Field("rejection_reason", "string", required=False, default=None),
    ])
    if values["decision"] == "REGISTER" and not values["registration_number"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "A REGISTER decision requires a registration_number.")
    if values["decision"] == "REJECT" and not values["rejection_reason"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "A REJECT decision requires a rejection_reason.")
    registration = lookup.registration(registration_id)
    project = db.projects.get(registration["project_id"])
    if registration["registration_state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_WARRANTY_STATE",
                       "Only a SUBMITTED registration can be decided.")
    if values["decision"] == "REGISTER":
        if project is None or project["version"] != registration["pinned_project_version"]:
            # The registration is left in SUBMITTED so the decision can be retried.
            raise ApiError("ERR_WARRANTY_PIN_STALE",
                           "The project has moved since submission; the pin is stale.")
        registration["registration_state"] = "REGISTERED"
        registration["registration_number"] = values["registration_number"]
        project["warranty_status"] = "REGISTERED"
    else:
        registration["registration_state"] = "REJECTED"
        registration["rejection_reason"] = values["rejection_reason"]
        if project is not None:
            project["warranty_status"] = "REJECTED"
    if project is not None:
        touch(project)
    touch(registration)
    return ok(serial.public(registration))


@warranty_bp.route("/cabling/warranty-registrations/<registration_id>/reopen",
                   methods=["POST"])
@require(PROJECT_MANAGER)
def reopen_registration(registration_id):
    no_body()
    registration = lookup.registration(registration_id)
    project = db.projects.get(registration["project_id"])
    if registration["registration_state"] != "REJECTED":
        raise ApiError("ERR_INVALID_WARRANTY_STATE",
                       "Only a REJECTED registration can be reopened.")
    registration["registration_state"] = "DRAFT"
    registration["rejection_reason"] = None
    registration["coverage_years"] = None
    registration["submitted_certified_link_count"] = None
    registration["pinned_project_version"] = None
    touch(registration)
    if project is not None:
        rollups.recompute_warranty_status_from_scratch(project)
        touch(project)
    return ok(serial.public(registration))
