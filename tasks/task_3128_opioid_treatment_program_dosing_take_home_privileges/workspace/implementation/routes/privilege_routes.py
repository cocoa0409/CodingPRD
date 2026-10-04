"""Take-home privileges and the carry ledgers."""
from flask import Blueprint, request

import db
from errors import ApiError
from response import ok_array_paged, ok_object, paginate_sorted, parse_pagination
from routes.common import (
    context,
    path_ledger,
    path_patient,
    path_program,
    require_patient_version,
)
from services import carry, entity, privilege as privilege_svc
from validation import int_field, text_field

bp = Blueprint("privileges", __name__)

READ_ROLES = [
    "ProgramAdministrator",
    "Physician",
    "Nurse",
    "MedicalDirector",
    "RegulatoryAuditor",
]
LEDGER_READ_ROLES = [
    "ProgramAdministrator",
    "Physician",
    "Nurse",
    "MedicalDirector",
    "RegulatoryAuditor",
]


@bp.route("/otp/take-home-privileges", methods=["POST"])
def create_privilege():
    actor = context(["MedicalDirector"])
    body = request.get_json(silent=True) or {}
    patient_id = text_field(body, "patient_id")
    patient = path_patient(patient_id)
    program = path_program(patient["program_id"])

    requested_carries = int_field(body, "requested_carries")
    carry_interval_days = int_field(body, "carry_interval_days")
    if carry_interval_days < 1 or carry_interval_days > 28:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "carry_interval_days must fall between 1 and 28 inclusive",
        )
    reissued_from = body.get("reissued_from_privilege_id")
    if reissued_from:
        if reissued_from not in db.take_home_privileges:
            raise ApiError(
                "ERR_PRIVILEGE_NOT_FOUND", "No TakeHomePrivilege with the supplied id"
            )

    # Priority 6: optimistic concurrency, before every state and safety check.
    require_patient_version(patient, body.get("expected_patient_version"))
    # Priority 9: carry operations require a NORMAL clinic.
    from services import program as program_svc

    program_svc.ensure_carry_posture(program)
    # Priority 23-style referential rule for the reissue path.
    if reissued_from:
        source = db.take_home_privileges.get(reissued_from)
        if source.get("decision") != "REVOKED":
            raise ApiError(
                "ERR_REISSUE_SOURCE_NOT_REVOKED",
                "reissued_from_privilege_id names a privilege that is not REVOKED",
            )
        if patient.get("status") != "ACTIVE":
            raise ApiError("ERR_PATIENT_NOT_ACTIVE", "Patient is not ACTIVE")

    row = privilege_svc.create_privilege(
        patient, requested_carries, carry_interval_days, actor, reissued_from=reissued_from
    )
    # The patient's ledger and the program pool both reflect the new hold.
    carry.ensure_ledger_for_patient(patient)
    return ok_object(entity.serialize_privilege(row), 201)


@bp.route("/otp/take-home-privileges", methods=["GET"])
def list_privileges():
    context(READ_ROLES)
    rows = list(db.take_home_privileges.values())
    for name in (
        "patient_id",
        "program_id",
        "decision",
        "exception_id",
        "reissued_from_privilege_id",
    ):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged([entity.serialize_privilege(r) for r in page], limit, offset, total)


@bp.route("/otp/take-home-privileges/<privilege_id>", methods=["GET"])
def read_privilege(privilege_id):
    context(READ_ROLES)
    row = privilege_svc.privilege_of(privilege_id)
    return ok_object(entity.serialize_privilege(row))


@bp.route("/otp/take-home-privileges/<privilege_id>/evaluate", methods=["POST"])
def evaluate(privilege_id):
    actor = context(["MedicalDirector"])
    row = privilege_svc.privilege_of(privilege_id)
    body = request.get_json(silent=True) or {}
    privilege_svc.evaluate(row, actor, body)
    return ok_object(entity.serialize_privilege(row))


@bp.route("/otp/take-home-privileges/<privilege_id>/revoke", methods=["POST"])
def revoke(privilege_id):
    actor = context(["MedicalDirector", "RegulatoryAuditor"])
    row = privilege_svc.privilege_of(privilege_id)
    privilege_svc.revoke(row, actor)
    return ok_object(entity.serialize_privilege(row))


# ---------------------------------------------------------------------------
# Carry ledgers
# ---------------------------------------------------------------------------
@bp.route("/otp/take-home-carry-ledgers", methods=["GET"])
def list_ledgers():
    context(LEDGER_READ_ROLES)
    rows = list(db.take_home_carry_ledgers.values())
    for name in ("patient_id", "program_id"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    for row in rows:
        carry.refresh_carry_ledger(row, bump=False)
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged([entity.serialize_carry_ledger(r) for r in page], limit, offset, total)


@bp.route("/otp/take-home-carry-ledgers/<ledger_id>", methods=["GET"])
def read_ledger(ledger_id):
    context(LEDGER_READ_ROLES)
    row = path_ledger(ledger_id)
    carry.refresh_carry_ledger(row, bump=False)
    return ok_object(entity.serialize_carry_ledger(row))