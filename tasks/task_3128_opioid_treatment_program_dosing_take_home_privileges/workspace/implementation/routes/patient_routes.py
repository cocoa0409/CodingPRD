"""Patients, admission, standing, discharge and the phase journal."""
from flask import Blueprint, request

import db
from constants import DISCHARGE_REASONS, PATIENT_STATUSES, TREATMENT_PHASES, TRANSPORTATION_TYPES
from errors import ApiError
from response import ok_array_paged, ok_object, paginate_sorted, parse_pagination
from routes.common import (
    context,
    path_patient,
    path_program,
    path_user,
    require_patient_version,
)
from services import carry, dose as dose_svc, entity, patient as patient_svc, patient_flow, stability
from validation import (
    bool_field,
    date_field,
    int_field,
    raw,
    text_field,
)

bp = Blueprint("patients", __name__)

READ_ROLES = [
    "ProgramAdministrator",
    "Physician",
    "Nurse",
    "Counselor",
    "MedicalDirector",
    "RegulatoryAuditor",
]
TRACKER_ROLES = [
    "ProgramAdministrator",
    "Physician",
    "Nurse",
    "MedicalDirector",
    "RegulatoryAuditor",
]


@bp.route("/otp/patients", methods=["POST"])
def create_patient():
    context(["ProgramAdministrator", "Physician"])
    body = request.get_json(silent=True) or {}
    program_id = text_field(body, "program_id")
    program = path_program(program_id)
    diagnosis_code = text_field(body, "diagnosis_code")
    if diagnosis_code not in ("F11_10", "F11_20", "F11_99"):
        raise ApiError(
            "ERR_INVALID_DIAGNOSIS_CODE",
            "diagnosis_code must be F11_10, F11_20 or F11_99",
        )
    transportation_type = text_field(body, "transportation_type")
    if transportation_type not in TRANSPORTATION_TYPES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "transportation_type must be one of %s" % ", ".join(TRANSPORTATION_TYPES),
        )
    patient = entity.make_patient(
        {
            "program_id": program_id,
            "full_name": text_field(body, "full_name"),
            "date_of_birth": date_field(body, "date_of_birth"),
            "government_id_hash": text_field(body, "government_id_hash"),
            "diagnosis_code": diagnosis_code,
            "home_state_code": text_field(body, "home_state_code").upper(),
            "home_address": text_field(body, "home_address"),
            "transportation_type": transportation_type,
            "one_way_travel_minutes": int_field(body, "one_way_travel_minutes"),
        }
    )
    db.patients[patient["id"]] = patient
    # §3.2 declares the counseling dimension's value at registration as the
    # default `CURRENT`, and §3.8's cadence calculation runs lazily on the next
    # read (as the phase journal's does). Recomputing it here would contradict
    # the declared default, since a patient with no completed plan review reads
    # deficient once three days have passed since admission. The recomputation
    # the phase change and the counseling-completion steps perform is unaffected.
    stability.refresh_patient(patient, publish="A")
    entity.refresh_tracker(patient)
    carry.ensure_ledger_for_patient(patient)
    program_svc_refresh(program)
    return ok_object(entity.serialize_patient(patient), 201)


def program_svc_refresh(program):
    from services import program as program_svc

    program_svc.refresh_program(program, bump=False)


@bp.route("/otp/patients", methods=["GET"])
def list_patients():
    context(READ_ROLES)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    rows = list(db.patients.values())
    if program_id:
        rows = [r for r in rows if r.get("program_id") == program_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    out = []
    for row in page:
        patient_svc.derive_time_in_treatment(row, db.clock_dt())
        row["stability_score"] = stability.direction_a(row)
        out.append(entity.serialize_patient(row))
    return ok_array_paged(out, limit, offset, total)


@bp.route("/otp/patients/<patient_id>", methods=["GET"])
def read_patient(patient_id):
    context(READ_ROLES)
    row = path_patient(patient_id)
    patient_svc.derive_time_in_treatment(row, db.clock_dt())
    row["stability_score"] = stability.direction_a(row)
    patient_svc.refresh_counseling(row)
    return ok_object(entity.serialize_patient(row))


@bp.route("/otp/patients/<patient_id>/confirm-diagnosis", methods=["POST"])
def confirm_diagnosis(patient_id):
    actor = context(["Physician"])
    row = path_patient(patient_id)
    patient_flow.confirm_diagnosis(row, actor)
    return ok_object(entity.serialize_patient(row))


@bp.route("/otp/patients/<patient_id>/reinstate", methods=["POST"])
def reinstate(patient_id):
    actor = context(["MedicalDirector"])
    row = path_patient(patient_id)
    patient_flow.reinstate(row, actor)
    return ok_object(entity.serialize_patient(row))


@bp.route("/otp/patients/<patient_id>/discharge", methods=["POST"])
def discharge(patient_id):
    actor = context(["Physician"])
    row = path_patient(patient_id)
    body = request.get_json(silent=True) or {}
    reason_code = body.get("reason_code")
    if reason_code not in DISCHARGE_REASONS:
        raise ApiError(
            "ERR_INVALID_DISCHARGE_REASON",
            "reason_code must be one of %s" % ", ".join(DISCHARGE_REASONS),
        )
    patient_flow.discharge(row, reason_code, actor)
    return ok_object(entity.serialize_patient(row))


@bp.route("/otp/patients/<patient_id>/complete-withdrawal", methods=["POST"])
def complete_withdrawal(patient_id):
    actor = context(["MedicalDirector"])
    row = path_patient(patient_id)
    patient_flow.complete_withdrawal(row, actor)
    return ok_object(entity.serialize_patient(row))


@bp.route("/otp/patients/<patient_id>/treatment-phase", methods=["PATCH"])
def move_phase(patient_id):
    context(["Physician", "MedicalDirector"])
    row = path_patient(patient_id)
    body = request.get_json(silent=True) or {}
    phase = body.get("treatment_phase")
    if phase not in TREATMENT_PHASES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "treatment_phase must be one of %s" % ", ".join(TREATMENT_PHASES),
        )
    reconciled_days = body.get("reconciled_days")
    if reconciled_days is not None:
        reconciled_days = int_field(body, "reconciled_days")
    patient_flow.move_phase(row, phase, reconciled_days)
    return ok_object(entity.serialize_patient(row))


@bp.route("/otp/patients/<patient_id>/time-in-treatment-tracker", methods=["GET"])
def tracker(patient_id):
    context(TRACKER_ROLES)
    row = path_patient(patient_id)
    tracker_row = db.time_in_treatment_trackers.get(patient_id)
    if tracker_row is None:
        tracker_row = entity.refresh_tracker(row)
    return ok_array_paged([entity.serialize_tracker(tracker_row)], 10, 0, 1)