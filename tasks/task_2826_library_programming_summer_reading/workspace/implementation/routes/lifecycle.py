"""Program confirmation, close-out, weather closure and cancellation."""

from flask import Blueprint

import calc
import derive
import lookup
import revision
import services
import store
import validate
from core import clock, date_of
from errors import ApiError
from web import Obj, endpoint

bp = Blueprint("lifecycle", __name__)

MANAGER = ("ProgramManager",)


def _require_partner_insurance(program, end_utc):
    expires_on = program["partner_insurance_expires_on"]
    if expires_on is None or expires_on < date_of(end_utc):
        raise ApiError("ERR_PARTNER_INSURANCE_LAPSED")


def _branch_overlap_load(program):
    """Closed public windows, CONFIRMED peers only, candidate counts itself."""
    load = 1
    for peer in store.DB["programs"].values():
        if peer["id"] == program["id"]:
            continue
        if peer["branch_id"] != program["branch_id"]:
            continue
        if peer["operational_status"] != "CONFIRMED":
            continue
        if calc.intervals_overlap_closed(
            program["start_utc"],
            program["end_utc"],
            peer["start_utc"],
            peer["end_utc"],
        ):
            load += 1
    return load


@bp.route("/library/programs/<program_id>/confirm", methods=["POST"])
@endpoint(MANAGER, mutating=True)
def confirm_program(user_id, role, program_id):
    program = lookup.program(program_id)

    if program["operational_status"] != "SCHEDULED":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if program["compliance_status"] in ("PENDING_SCREENING", "BLOCKED"):
        raise ApiError("ERR_PROGRAM_COMPLIANCE_BLOCKED")

    confirmed_reservation = None
    if program["delivery_mode"] == "PARTNER_SITE":
        _require_partner_insurance(program, program["end_utc"])
    else:
        for reservation in derive.program_reservations(program["id"]):
            if reservation["status"] == "CONFIRMED":
                confirmed_reservation = reservation
                break
        if confirmed_reservation is None:
            raise ApiError("ERR_NO_CONFIRMED_ROOM")

    branch = store.get("branches", program["branch_id"])
    if branch is not None:
        if _branch_overlap_load(program) > branch["overlapping_program_capacity"]:
            raise ApiError("ERR_BRANCH_STAFFING_CAPACITY_EXCEEDED")

    plan = services.supply_draw_plan(program)
    if plan is None:
        raise ApiError("ERR_SUPPLY_INVENTORY_INSUFFICIENT")
    lines, subtotal = plan

    committed = calc.materials_commitment_cents(subtotal)
    if committed > program["materials_budget_cents"]:
        raise ApiError("ERR_MATERIALS_BUDGET_EXCEEDED")

    guard = services.PostureGuard()
    guard.watch(program)
    services.apply_supply_draw(program, lines)
    program["materials_committed_cents"] = committed
    if confirmed_reservation is not None:
        program["confirmed_room_capacity"] = confirmed_reservation[
            "effective_capacity_seats"
        ]
    else:
        program["confirmed_room_capacity"] = 0
    program["operational_status"] = "CONFIRMED"
    guard.settle()
    revision.mark(program)
    return Obj("programs", program)


@bp.route("/library/programs/<program_id>/close-out", methods=["POST"])
@endpoint(MANAGER, mutating=True)
def close_out_program(user_id, role, program_id):
    payload = validate.body()
    verified = validate.integer_field(
        payload, "verified_registrant_attendance", minimum=0
    )
    drop_in = validate.integer_field(payload, "drop_in_headcount", minimum=0)
    surveys = validate.integer_field(payload, "surveys_collected", minimum=0)
    program = lookup.program(program_id)

    if program["operational_status"] != "CONFIRMED":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if clock.now() < program["end_utc"]:
        raise ApiError("ERR_PROGRAM_NOT_YET_ENDED")
    if verified > program["registered_count"]:
        raise ApiError("ERR_ATTENDANCE_EXCEEDS_REGISTRATIONS")
    if surveys > verified + drop_in:
        raise ApiError("ERR_SURVEY_COUNT_EXCEEDS_ATTENDANCE")

    guard = services.PostureGuard()
    guard.watch(program)

    program["verified_registrant_attendance"] = verified
    program["drop_in_headcount"] = drop_in
    program["surveys_collected"] = surveys
    program.update(calc.attendance_outcomes(program, verified, drop_in, surveys))

    # Materials: committed money becomes spend, reserved stock becomes issued.
    services.issue_supply_draw(program)
    program["materials_spent_cents"] += program["materials_committed_cents"]
    program["materials_committed_cents"] = 0

    for contract in derive.program_contracts(program["id"]):
        if contract["status"] == "EXECUTED":
            contract["status"] = "COMPLETED"
            revision.mark(contract)
    program["presenter_fee_spent_cents"] += program["presenter_fee_committed_cents"]
    program["presenter_fee_committed_cents"] = 0

    for reservation in derive.program_reservations(program["id"]):
        if reservation["status"] in ("HELD", "CONFIRMED"):
            reservation["status"] = "RELEASED"
            revision.mark(reservation)

    program["operational_status"] = "CLOSED_OUT"
    guard.settle()
    revision.mark(program)
    return Obj("programs", program)


@bp.route("/library/programs/<program_id>/weather-close", methods=["POST"])
@endpoint(MANAGER, mutating=True)
def weather_close_program(user_id, role, program_id):
    payload = validate.body()
    closure_reason = validate.string_field(payload, "closure_reason")
    program = lookup.program(program_id)

    if program["operational_status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if clock.now() >= program["end_utc"]:
        raise ApiError("ERR_WEATHER_WINDOW_PASSED")

    guard = services.PostureGuard()
    guard.watch(program)
    services.cancel_program_contracts(program, "WEATHER")
    services.return_supply_draw(program)
    services.release_reservations(program)
    program["closure_reason"] = closure_reason
    program["operational_status"] = "WEATHER_CLOSED"
    guard.settle()
    revision.mark(program)
    return Obj("programs", program)


@bp.route("/library/programs/<program_id>/cancel", methods=["POST"])
@endpoint(MANAGER, mutating=True)
def cancel_program(user_id, role, program_id):
    payload = validate.body()
    closure_reason = validate.string_field(payload, "closure_reason")
    program = lookup.program(program_id)

    if program["operational_status"] not in ("DRAFT", "SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_PROGRAM_STATE_INVALID")

    guard = services.PostureGuard()
    guard.watch(program)
    services.cancel_program_contracts(program, "LIBRARY")
    services.return_supply_draw(program)
    services.release_reservations(program)
    program["closure_reason"] = closure_reason
    program["operational_status"] = "CANCELLED"
    guard.settle()
    revision.mark(program)
    return Obj("programs", program)
