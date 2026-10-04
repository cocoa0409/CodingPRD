"""Guest dosing arrangements (PRD 3.11)."""
from flask import Blueprint, request

import db
from errors import ApiError
from response import ok_array_paged, ok_object, paginate_sorted, parse_pagination
from routes.common import context, path_patient, path_program, require_patient_version
from services import entity, guest as guest_svc
from validation import date_field, text_field

bp = Blueprint("guest", __name__)

READ_ROLES = ["ProgramAdministrator", "Physician", "Nurse", "MedicalDirector", "RegulatoryAuditor"]


@bp.route("/otp/guest-dosing-arrangements", methods=["POST"])
def create_arrangement():
    context(["ProgramAdministrator"])
    body = request.get_json(silent=True) or {}
    patient = path_patient(text_field(body, "patient_id"))
    receiving_program_id = text_field(body, "receiving_program_id")
    path_program(receiving_program_id)
    travel_start_date = date_field(body, "travel_start_date")
    travel_end_date = date_field(body, "travel_end_date")

    # Priority 6: optimistic concurrency against the travelling patient.
    require_patient_version(patient, body.get("expected_patient_version"))

    row = guest_svc.create_arrangement(
        patient,
        receiving_program_id,
        travel_start_date,
        travel_end_date,
        None,
    )
    return ok_object(entity.serialize_arrangement(row), 201)


@bp.route("/otp/guest-dosing-arrangements", methods=["GET"])
def list_arrangements():
    context(READ_ROLES)
    rows = list(db.guest_dosing_arrangements.values())
    for name in ("patient_id", "originating_program_id", "receiving_program_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged(
        [entity.serialize_arrangement(r) for r in page], limit, offset, total
    )


@bp.route("/otp/guest-dosing-arrangements/<arrangement_id>", methods=["GET"])
def read_arrangement(arrangement_id):
    context(READ_ROLES)
    row = guest_svc.arrangement_of(arrangement_id)
    return ok_object(entity.serialize_arrangement(row))


@bp.route("/otp/guest-dosing-arrangements/<arrangement_id>/transmit", methods=["POST"])
def transmit(arrangement_id):
    actor = context(["ProgramAdministrator"])
    row = guest_svc.arrangement_of(arrangement_id)
    guest_svc.transmit(row, actor)
    return ok_object(entity.serialize_arrangement(row))


@bp.route("/otp/guest-dosing-arrangements/<arrangement_id>/acknowledge", methods=["POST"])
def acknowledge(arrangement_id):
    actor = context(["Nurse"])
    row = guest_svc.arrangement_of(arrangement_id)
    guest_svc.acknowledge(row, actor)
    return ok_object(entity.serialize_arrangement(row))


@bp.route("/otp/guest-dosing-arrangements/<arrangement_id>/reject", methods=["POST"])
def reject(arrangement_id):
    actor = context(["Nurse"])
    row = guest_svc.arrangement_of(arrangement_id)
    guest_svc.reject(row, actor)
    return ok_object(entity.serialize_arrangement(row))


@bp.route("/otp/guest-dosing-arrangements/<arrangement_id>/close", methods=["POST"])
def close(arrangement_id):
    actor = context(["ProgramAdministrator"])
    row = guest_svc.arrangement_of(arrangement_id)
    guest_svc.close(row, actor)
    return ok_object(entity.serialize_arrangement(row))


@bp.route("/otp/guest-dosing-arrangements/<arrangement_id>/cancel", methods=["POST"])
def cancel(arrangement_id):
    actor = context(["ProgramAdministrator"])
    row = guest_svc.arrangement_of(arrangement_id)
    guest_svc.cancel(row, actor)
    return ok_object(entity.serialize_arrangement(row))