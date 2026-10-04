"""Take-home exceptions (PRD 3.9)."""
from flask import Blueprint, request

import db
from constants import EXCEPTION_TYPES
from errors import ApiError
from response import ok_array_paged, ok_object, paginate_sorted, parse_pagination
from routes.common import (
    context,
    path_patient,
    require_privilege_version,
)
from services import entity, exception_flow
from validation import int_field, text_field

bp = Blueprint("exceptions", __name__)

READ_ROLES = ["ProgramAdministrator", "Physician", "MedicalDirector", "RegulatoryAuditor"]
FULL_READ_ROLES = READ_ROLES + ["Nurse"]


def _challenged_privilege(patient, named_id=None):
    """The privilege a documented exception attaches to.

    An exception exists to lift a patient past a denial, so the privilege it
    challenges is the patient's `DENIED` row. An explicit identifier is honoured
    when supplied, provided it belongs to the patient.
    """
    if named_id:
        row = db.take_home_privileges.get(named_id)
        if row is not None and row.get("patient_id") == patient["id"]:
            return row
        return None
    candidates = [
        row
        for row in db.take_home_privileges.values()
        if row.get("patient_id") == patient["id"] and row.get("decision") == "DENIED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (str(row.get("created_at", "")), str(row.get("id", ""))))
    return candidates[-1]


@bp.route("/otp/take-home-exceptions", methods=["POST"])
def create_exception():
    actor = context(["Physician"])
    body = request.get_json(silent=True) or {}
    patient_id = text_field(body, "patient_id")
    patient = path_patient(patient_id)
    requested_carries = int_field(body, "requested_carries")
    exception_type = text_field(body, "exception_type")
    if exception_type not in EXCEPTION_TYPES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "exception_type must be one of %s" % ", ".join(EXCEPTION_TYPES),
        )
    clinical_justification = body.get("clinical_justification")
    supervisor_id = text_field(body, "supervisor_id")
    # §3.9 declares the create input as patient_id, requested_carries,
    # exception_type, clinical_justification, supervisor_id and
    # expected_privilege_version; the challenged privilege is not a client input.
    # It is resolved from the patient — the DENIED privilege the exception is
    # meant to challenge — and §2.10 checks expected_privilege_version against
    # that row. A privilege_id supplied by the client is honoured only as a
    # disambiguator when the patient holds more than one DENIED row.
    privilege = _challenged_privilege(patient, body.get("privilege_id"))
    if privilege is None:
        raise ApiError(
            "ERR_PRIVILEGE_NOT_FOUND",
            "The patient holds no take-home privilege for the exception to challenge",
        )

    # Priority 6: optimistic concurrency against the challenged privilege.
    require_privilege_version(privilege, body.get("expected_privilege_version"))

    row = exception_flow.create_exception(
        patient,
        requested_carries,
        exception_type,
        clinical_justification,
        supervisor_id,
        actor,
        privilege=privilege,
    )
    return ok_object(entity.serialize_exception(row), 201)


@bp.route("/otp/take-home-exceptions", methods=["GET"])
def list_exceptions():
    context(READ_ROLES)
    rows = list(db.take_home_exceptions.values())
    for name in ("patient_id", "program_id", "status", "requesting_physician_id", "supervisor_id"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged([entity.serialize_exception(r) for r in page], limit, offset, total)


@bp.route("/otp/take-home-exceptions/<exception_id>", methods=["GET"])
def read_exception(exception_id):
    context(FULL_READ_ROLES)
    row = exception_flow.exception_of(exception_id)
    return ok_object(entity.serialize_exception(row))


@bp.route("/otp/take-home-exceptions/<exception_id>/route", methods=["POST"])
def route(exception_id):
    actor = context(["Physician"])
    row = exception_flow.exception_of(exception_id)
    exception_flow.route(row, actor)
    return ok_object(entity.serialize_exception(row))


@bp.route("/otp/take-home-exceptions/<exception_id>/decision", methods=["POST"])
def decision(exception_id):
    actor = context(["MedicalDirector"])
    row = exception_flow.exception_of(exception_id)
    body = request.get_json(silent=True) or {}
    value = body.get("decision")
    granted = body.get("granted_carries")
    if granted is not None:
        granted = int_field(body, "granted_carries")
    if value not in ("GRANT", "DENY"):
        raise ApiError("ERR_INVALID_REQUEST", "decision must be GRANT or DENY")
    exception_flow.decide(row, value, granted, actor)
    return ok_object(entity.serialize_exception(row))


@bp.route("/otp/take-home-exceptions/<exception_id>/revoke", methods=["POST"])
def revoke(exception_id):
    actor = context(["MedicalDirector"])
    row = exception_flow.exception_of(exception_id)
    exception_flow.revoke(row, actor)
    return ok_object(entity.serialize_exception(row))