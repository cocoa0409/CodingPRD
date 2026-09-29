"""Operators, airframes, pilots, the logbook audit and the logical clock."""

from flask import Blueprint, g

import auth
import calc
import constants as C
import derive
import envelope
import serialize
import services
import validate as V
from errors import ApiError
from store import db, new_record, touch

bp = Blueprint("registry", __name__)

ALL = C.ALL_ROLES
WRITE_REGISTER = ["Underwriter", "Broker"]


# --- operators ----------------------------------------------------------------

@bp.route("/aviation/operators", methods=["POST"])
@auth.endpoint(WRITE_REGISTER)
def create_operator():
    body = V.json_body()
    legal_name = V.get_str(body, "legal_name")
    operator_type = V.get_str(body, "operator_type")
    home_base_icao = V.get_str(body, "home_base_icao")
    aoc_number = V.get_str(body, "aoc_number", required=False)

    V.check_len(legal_name, "legal_name", 1, 120, non_blank=True)
    V.check_enum(operator_type, "operator_type", C.OPERATOR_TYPES)
    V.check_len(home_base_icao, "home_base_icao", 4, 4)
    V.check_pattern(home_base_icao, "home_base_icao", r"^[A-Z]{4}$", "exactly four uppercase letters")
    if aoc_number is not None:
        V.check_len(aoc_number, "aoc_number", 4, 16)
        V.check_pattern(aoc_number, "aoc_number", r"^[A-Z0-9-]+$",
                        "uppercase letters, digits and hyphens only")

    if operator_type == "AIR_CARRIER" and aoc_number is None:
        raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED",
                       "aoc_number is mandatory when operator_type is AIR_CARRIER.")

    rec = new_record(db.operators, {
        "legal_name": legal_name,
        "operator_type": operator_type,
        "aoc_number": aoc_number,
        "home_base_icao": home_base_icao,
    })
    return envelope.ok(serialize.operator(rec), 201)


@bp.route("/aviation/operators/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_operator(row_id):
    rec = services.get_operator(row_id)
    auth.scope_operator_id(rec["id"])
    return envelope.ok(serialize.operator(rec))


# --- aircraft -----------------------------------------------------------------

@bp.route("/aviation/aircraft", methods=["POST"])
@auth.endpoint(WRITE_REGISTER)
def create_aircraft():
    body = V.json_body()
    registration_mark = V.get_str(body, "registration_mark")
    aircraft_class = V.get_str(body, "aircraft_class")
    manufacture_year = V.get_int(body, "manufacture_year")
    hull_new_value_cents = V.get_int(body, "hull_new_value_cents")
    seat_count = V.get_int(body, "seat_count")
    max_takeoff_weight_kg = V.get_int(body, "max_takeoff_weight_kg")

    V.check_len(registration_mark, "registration_mark", 3, 8)
    V.check_pattern(registration_mark, "registration_mark", r"^[A-Z0-9-]+$",
                    "uppercase letters, digits and hyphens only")
    V.check_enum(aircraft_class, "aircraft_class", C.AIRCRAFT_CLASSES)
    V.check_range(manufacture_year, "manufacture_year", 1950, 2026)
    V.check_range(hull_new_value_cents, "hull_new_value_cents", 1)
    V.check_range(seat_count, "seat_count", 1, 500)
    V.check_range(max_takeoff_weight_kg, "max_takeoff_weight_kg", 1)

    for other in db.aircraft.values():
        if other["registration_mark"] == registration_mark:
            raise ApiError("ERR_DUPLICATE_REGISTRATION")

    rec = new_record(db.aircraft, {
        "registration_mark": registration_mark,
        "aircraft_class": aircraft_class,
        "manufacture_year": manufacture_year,
        "hull_new_value_cents": hull_new_value_cents,
        "seat_count": seat_count,
        "max_takeoff_weight_kg": max_takeoff_weight_kg,
    })
    return envelope.ok(serialize.aircraft(rec), 201)


@bp.route("/aviation/aircraft/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_aircraft(row_id):
    rec = services.get_aircraft(row_id)
    return envelope.ok(serialize.aircraft(rec))


# --- pilots -------------------------------------------------------------------

@bp.route("/aviation/pilots", methods=["POST"])
@auth.endpoint(WRITE_REGISTER)
def create_pilot():
    body = V.json_body()
    pilot_name = V.get_str(body, "pilot_name")
    license_type = V.get_str(body, "license_type")
    total_logged_hours = V.get_int(body, "total_logged_hours")
    hours_on_type = V.get_int(body, "hours_on_type")
    last_training_completed_at = V.get_instant(body, "last_training_completed_at")
    medical_expires_at = V.get_instant(body, "medical_expires_at")
    instrument_rated = V.get_bool(body, "instrument_rated", required=False, default=False)

    V.check_len(pilot_name, "pilot_name", 1, 120)
    V.check_enum(license_type, "license_type", C.LICENSE_TYPES)
    V.check_range(total_logged_hours, "total_logged_hours", 0)
    V.check_range(hours_on_type, "hours_on_type", 0)
    if hours_on_type > total_logged_hours:
        raise V.invalid("hours_on_type may not exceed total_logged_hours.")

    rec = new_record(db.pilots, {
        "pilot_name": pilot_name,
        "license_type": license_type,
        "total_logged_hours": total_logged_hours,
        "hours_on_type": hours_on_type,
        "instrument_rated": instrument_rated,
        "last_training_completed_at": last_training_completed_at,
        "medical_expires_at": medical_expires_at,
        "verified_total_hours": None,
        "verified_hours_on_type": None,
        "verified_at": None,
    })
    return envelope.ok(serialize.pilot(rec), 201)


@bp.route("/aviation/pilots/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_pilot(row_id):
    rec = services.get_pilot(row_id)
    return envelope.ok(serialize.pilot(rec))


@bp.route("/aviation/pilots/<row_id>/hours-verifications", methods=["POST"])
@auth.endpoint(["Underwriter"])
def verify_pilot_hours(row_id):
    pilot = services.get_pilot(row_id)
    body = V.json_body()
    verified_total_hours = V.get_int(body, "verified_total_hours")
    verified_hours_on_type = V.get_int(body, "verified_hours_on_type")
    V.check_range(verified_total_hours, "verified_total_hours", 0)
    V.check_range(verified_hours_on_type, "verified_hours_on_type", 0)

    pilot["verified_total_hours"] = verified_total_hours
    pilot["verified_hours_on_type"] = verified_hours_on_type
    pilot["verified_at"] = db.clock
    touch(pilot)

    for schedule in derive.schedules_of_pilot(pilot["id"]):
        if schedule["coverage_status"] not in C.LIVE_COVERAGE:
            continue
        policy = db.policies[schedule["policy_id"]]
        old_premium = services.rerate_schedule(schedule, policy, refresh_basis=True, pilot=pilot)
        touch(schedule)
        services.post_rerate_adjustment(
            schedule, policy, old_premium,
            "re-rate of schedule %s on verified hours" % schedule["id"])
        _apply_warranty_test(schedule, pilot)

    return envelope.ok(serialize.pilot(pilot), 201)


def _apply_warranty_test(schedule, pilot):
    """PRD 3.5: the audited figures are tested against the schedule's frozen minima."""
    passes = (
        pilot["verified_total_hours"] >= schedule["warranted_min_total_hours"]
        and pilot["verified_hours_on_type"] >= schedule["warranted_min_hours_on_type"]
        and (not C.WARRANTY_REQUIRES_INSTRUMENT[schedule["use_class"]]
             or bool(pilot["instrument_rated"]))
    )
    if passes:
        if schedule["warranty_status"] == "PENDING_EVIDENCE":
            schedule["warranty_status"] = "COMPLIANT"
            schedule["warranty_breach_reason"] = None
            touch(schedule)
        return
    if schedule["warranty_status"] in ("PENDING_EVIDENCE", "COMPLIANT"):
        schedule["warranty_status"] = "BREACHED"
        schedule["warranty_breach_reason"] = "VERIFIED_HOURS_BELOW_WARRANTY"
        touch(schedule)
        services.suspend_for_breach(schedule)


# --- logical clock ------------------------------------------------------------

@bp.route("/aviation/_clock/set_current_utc", methods=["POST"])
@auth.endpoint(ALL)
def set_clock():
    body = V.json_body()
    current_utc = V.get_instant(body, "current_utc")
    db.clock = current_utc
    services.expiry_sweep()
    return envelope.ok({})
