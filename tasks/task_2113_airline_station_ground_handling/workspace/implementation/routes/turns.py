from flask import Blueprint

import constants as C
import validators as V
from auth import authorize
from domain import (
    apply_changes, bank_staffing_fallback, recompute_bank_rollup, recompute_station_otp,
    recompute_turn_coverage, resources_of_turn, serialize_turn, set_service_hold,
)
from envelope import filter_equals, paginate, respond_object
from errors import ApiError
from store import (
    as_dt, db, new_record, now_stamp, ordered, plus_minutes, require, whole_minutes_between,
)

bp = Blueprint("turns", __name__)


@bp.post("/turns")
def create_turn():
    authorize([C.ROLE_DUTY_OFFICER])
    payload = V.body()

    station_id = V.req_string(payload, "station_id")
    flight_bank_id = V.req_string(payload, "flight_bank_id")
    flight_number = V.req_string(payload, "flight_number")
    turn_type = V.req_enum(payload, "turn_type", C.TURN_TYPES)
    scheduled_in = V.req_datetime(payload, "scheduled_in")
    scheduled_out = V.req_datetime(payload, "scheduled_out")

    station = require(db.stations, station_id, "Station")
    bank = require(db.flight_banks, flight_bank_id, "FlightBank")

    if bank["station_id"] != station["id"]:
        raise ApiError("ERR_STATION_SCOPE_MISMATCH")

    if bank["bank_status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_INVALID_STATE", "The flight bank takes no further turnarounds.")
    if station["status"] != "OPEN":
        raise ApiError("ERR_STATION_NOT_OPEN")
    if station["oversight_posture"] == "RESTRICTED":
        raise ApiError("ERR_STATION_POSTURE_RESTRICTED")

    sched_in = as_dt(scheduled_in)
    sched_out = as_dt(scheduled_out)
    if sched_in < as_dt(bank["window_start"]) or sched_out > as_dt(bank["window_end"]):
        raise ApiError("ERR_TURN_WINDOW_OUTSIDE_BANK")

    turn = new_record("Turn", {
        "station_id": station["id"],
        "flight_bank_id": bank["id"],
        "flight_number": flight_number,
        "turn_type": turn_type,
        "scheduled_in": scheduled_in,
        "scheduled_out": scheduled_out,
        "actual_in": None,
        "actual_out": None,
        "scheduled_ground_minutes": whole_minutes_between(sched_in, sched_out),
        "actual_ground_minutes": None,
        "delay_minutes": None,
        "delay_code": None,
        "otp_result": "PENDING",
        "status": "SCHEDULED",
        "required_agent_count": C.REQUIRED_AGENTS[turn_type],
        "required_gse_count": C.REQUIRED_GSE[turn_type],
        "assigned_agent_count": 0,
        "assigned_gse_count": 0,
        "billed": False,
    })
    db.turns[turn["id"]] = turn

    coverage = recompute_bank_rollup(bank)
    if coverage < C.APPROVE_MIN_COVERAGE_PCT:
        bank_staffing_fallback(bank)

    return respond_object(serialize_turn(turn), 201)


@bp.get("/turns/<turn_id>")
def read_turn(turn_id):
    authorize(C.ALL_ROLES)
    turn = require(db.turns, turn_id, "Turn")
    return respond_object(serialize_turn(turn))


@bp.get("/turns")
def list_turns():
    authorize(C.ALL_ROLES)
    records = filter_equals(db.turns.values(), {
        "station_id": "station_id",
        "flight_bank_id": "flight_bank_id",
        "status": "status",
        "otp_result": "otp_result",
    })
    return paginate(ordered(records), serialize_turn)


def _complete_turn(turn, station, actual_out_raw, delay_code):
    actual_in = as_dt(turn["actual_in"])
    actual_out_value = actual_out_raw if actual_out_raw is not None else now_stamp()
    actual_out = as_dt(actual_out_value)
    if actual_in is not None and actual_out < actual_in:
        raise ApiError("ERR_INVALID_REQUEST", "actual_out may not be earlier than actual_in.")

    actual_ground = whole_minutes_between(actual_in, actual_out) if actual_in else None
    delay_minutes = max(0, whole_minutes_between(as_dt(turn["scheduled_out"]), actual_out))

    if delay_minutes <= station["otp_tolerance_minutes"]:
        otp_result = "ON_TIME"
    elif delay_code in C.EXCLUDED_DELAY_CODES:
        otp_result = "EXCLUDED"
    else:
        otp_result = "DELAYED"

    apply_changes(turn, {
        "status": "COMPLETED",
        "actual_out": actual_out_value,
        "actual_ground_minutes": actual_ground,
        "delay_minutes": delay_minutes,
        "delay_code": delay_code,
        "otp_result": otp_result,
    })

    for resource in ordered(resources_of_turn(turn["id"])):
        if resource["status"] != "COMMITTED":
            continue
        apply_changes(resource, {"status": "RELEASED"})
        if resource["resource_kind"] == "AGENT":
            agent = db.agents.get(resource["agent_id"])
            if agent:
                from domain import recompute_agent_ledger
                recompute_agent_ledger(agent)
        else:
            unit = db.gse_units.get(resource["gse_unit_id"])
            if unit:
                from domain import recompute_gse_ledger
                recompute_gse_ledger(unit)
                apply_changes(unit, {"cycles_since_service": unit["cycles_since_service"] + 1})
                if unit["cycles_since_service"] >= unit["service_interval_cycles"] \
                        and unit["status"] == "AVAILABLE":
                    apply_changes(unit, {"status": "IN_MAINTENANCE"})
                    set_service_hold(unit, db.clock, plus_minutes(db.clock, C.SERVICE_HOLD_MINUTES))
    recompute_turn_coverage(turn)
    recompute_station_otp(station)


@bp.post("/turns/<turn_id>/lifecycle")
def turn_lifecycle(turn_id):
    authorize([C.ROLE_DUTY_OFFICER])
    turn = require(db.turns, turn_id, "Turn")
    payload = V.body()
    action = V.req_enum(payload, "action", C.TURN_ACTIONS)
    actual_in = V.opt_datetime(payload, "actual_in")
    actual_out = V.opt_datetime(payload, "actual_out")
    delay_code = V.opt_enum(payload, "delay_code", C.DELAY_CODES)
    V.opt_string(payload, "reason")

    station = db.stations[turn["station_id"]]
    bank = db.flight_banks.get(turn["flight_bank_id"])

    if action == "START":
        if turn["status"] != "RESOURCED":
            raise ApiError("ERR_INVALID_STATE")
        if station["status"] != "OPEN":
            raise ApiError("ERR_STATION_NOT_OPEN")
        if bank is None or bank["bank_status"] not in ("PUBLISHED", "LOCKED"):
            raise ApiError("ERR_BANK_NOT_PUBLISHED")
        if bank["staffing_status"] != "APPROVED":
            raise ApiError("ERR_STAFFING_NOT_APPROVED")
        apply_changes(turn, {
            "status": "IN_PROGRESS",
            "actual_in": actual_in if actual_in is not None else now_stamp(),
        })
        for resource in ordered(resources_of_turn(turn["id"])):
            if resource["status"] == "RESERVED":
                apply_changes(resource, {"status": "COMMITTED"})
    elif action == "COMPLETE":
        if turn["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE")
        _complete_turn(turn, station, actual_out, delay_code)
    else:  # CANCEL
        if turn["status"] not in ("SCHEDULED", "RESOURCED", "DISRUPTED"):
            raise ApiError("ERR_INVALID_STATE")
        if turn["billed"]:
            raise ApiError("ERR_TURN_NOT_BILLABLE", "The turnaround already carries a charge.")
        apply_changes(turn, {"status": "CANCELLED"})
        for resource in ordered(resources_of_turn(turn["id"])):
            if resource["status"] in ("RESERVED", "COMMITTED"):
                from domain import cancel_resource
                cancel_resource(resource, C.CANCEL_TURN_CANCELLED)
        if bank:
            recompute_bank_rollup(bank)

    return respond_object(serialize_turn(turn))
