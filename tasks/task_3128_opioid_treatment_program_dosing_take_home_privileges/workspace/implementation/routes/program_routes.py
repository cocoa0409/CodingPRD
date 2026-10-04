"""Programs and the program carry quota ledger."""
from flask import Blueprint, request

import db
from constants import OPEN_DAYS
from errors import ApiError
from response import ok_array_paged, ok_object, paginate_sorted, parse_pagination
from routes.common import context, path_program
from services import carry, entity, program as program_svc
from validation import (
    bool_field,
    int_field,
    num_field,
    text_field,
)

bp = Blueprint("programs", __name__)

READ_ROLES = [
    "ProgramAdministrator",
    "Physician",
    "Nurse",
    "Counselor",
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

def _valid_hhmm(value):
    parts = str(value).split(":")
    if len(parts) != 2:
        return False
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


@bp.route("/otp/programs", methods=["POST"])
def create_program():
    context(["ProgramAdministrator"])
    body = request.get_json(silent=True) or {}
    name = text_field(body, "name")
    state_code = text_field(body, "state_code")
    if len(state_code) != 2:
        raise ApiError("ERR_INVALID_REQUEST", "state_code must be a two-letter US state code")
    hours_start = text_field(body, "clinic_hours_start")
    hours_end = text_field(body, "clinic_hours_end")
    if not _valid_hhmm(hours_start) or not _valid_hhmm(hours_end):
        raise ApiError("ERR_INVALID_REQUEST", "clinic hours must be HH:MM in 24-hour form")
    open_days = body.get("open_days")
    if not isinstance(open_days, list) or not open_days:
        raise ApiError("ERR_INVALID_REQUEST", "open_days must be a non-empty array")
    for day in open_days:
        if day not in OPEN_DAYS:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "open_days entries must be drawn from %s" % ", ".join(OPEN_DAYS),
            )
    slots = int_field(body, "max_daily_dose_slots")
    if slots < 0:
        raise ApiError("ERR_INVALID_REQUEST", "max_daily_dose_slots must not be negative")
    payload = {
        "name": name,
        "state_code": state_code.upper(),
        "clinic_hours_start": hours_start,
        "clinic_hours_end": hours_end,
        "open_days": list(open_days),
        "max_daily_dose_slots": slots,
        "max_daily_mg_methadone": num_field(body, "max_daily_mg_methadone", 120.0),
        "max_daily_mg_buprenorphine": num_field(body, "max_daily_mg_buprenorphine", 24.0),
        "guest_dosing_enabled": bool_field(body, "guest_dosing_enabled", True),
        "dose_checkin_grace_minutes": int_field(body, "dose_checkin_grace_minutes", 30),
    }
    row = entity.make_program(payload)
    db.programs[row["id"]] = row
    return ok_object(entity.serialize_program(row), 201)


@bp.route("/otp/programs", methods=["GET"])
def list_programs():
    context(READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows, total = paginate_sorted(list(db.programs.values()), limit, offset)
    for row in rows:
        program_svc.refresh_program(row, bump=False)
    return ok_array_paged(
        [entity.serialize_program(r) for r in rows], limit, offset, total
    )


@bp.route("/otp/programs/<program_id>", methods=["GET"])
def read_program(program_id):
    context(READ_ROLES)
    row = path_program(program_id)
    program_svc.refresh_program(row, bump=False)
    return ok_object(entity.serialize_program(row))


@bp.route("/otp/programs/<program_id>/suspend", methods=["POST"])
def suspend_program(program_id):
    actor = context(["RegulatoryAuditor"])
    row = path_program(program_id)
    program_svc.suspend_program(row, actor)
    return ok_object(entity.serialize_program(row))


@bp.route("/otp/programs/<program_id>/resume", methods=["POST"])
def resume_program(program_id):
    actor = context(["RegulatoryAuditor"])
    row = path_program(program_id)
    program_svc.resume_program(row, actor)
    return ok_object(entity.serialize_program(row))


@bp.route("/otp/programs/<program_id>/carry-quota", methods=["POST"])
def open_carry_quota(program_id):
    context(["ProgramAdministrator"])
    program = path_program(program_id)
    if carry.quota_for_program(program_id) is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "This program already has a carry quota ledger",
        )
    body = request.get_json(silent=True) or {}
    allotted = int_field(body, "allotted_carries")
    if allotted < 0:
        raise ApiError("ERR_INVALID_REQUEST", "allotted_carries must not be negative")
    row = entity.make_carry_quota_ledger(program_id, allotted)
    db.carry_quota_ledgers[row["id"]] = row
    carry.refresh_quota(row, bump=False)
    program_svc.refresh_program(program, bump=False)
    return ok_object(entity.serialize_carry_quota_ledger(row), 201)


@bp.route("/otp/programs/<program_id>/carry-quota", methods=["GET"])
def read_carry_quota(program_id):
    context(LEDGER_READ_ROLES)
    path_program(program_id)
    row = carry.quota_for_program(program_id)
    if row is None:
        raise ApiError(
            "ERR_CARRY_LEDGER_NOT_FOUND",
            "No CarryQuotaLedger exists for the program",
        )
    carry.refresh_quota(row, bump=False)
    return ok_array_paged([entity.serialize_carry_quota_ledger(row)], 10, 0, 1)