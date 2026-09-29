"""State distribution licences and wholesaler appointments."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascades
import derive
import envelope
import helpers
import store
import validation
from errors import ApiError
from validation import ALL_ROLES, authenticate

bp = Blueprint("licensing", __name__)

LICENSE_TYPES = ("SELF_DISTRIBUTION", "WHOLESALER_ONLY")
LICENSE_STATUSES = ("ACTIVE", "SUSPENDED", "EXPIRED")
APPOINTMENT_STATES = ("PROPOSED", "ACTIVE", "TERMINATION_REQUESTED", "TERMINATED")
GOOD_CAUSE_CODES = ("NONPAYMENT", "BREACH_OF_CONTRACT", "LOSS_OF_LICENSE", "VOLUNTARY_MUTUAL")
TERMINATION_PHASES = ("REQUEST", "FINALIZE", "WITHDRAW")
LIVE_APPOINTMENT_STATES = ("ACTIVE", "TERMINATION_REQUESTED")


# ---------------------------------------------------------------------------
# state licences
# ---------------------------------------------------------------------------

@bp.get("/state-licenses")
def list_licenses():
    authenticate(ALL_ROLES)
    status = validation.query_enum("status", LICENSE_STATUSES)
    license_type = validation.query_enum("license_type", LICENSE_TYPES)
    franchise_state = validation.query_bool("franchise_state")
    state_code = validation.query_string("state_code")
    cascades.refresh_all_license_expiry()

    def predicate(row):
        return (helpers.matches(row, "status", status)
                and helpers.matches(row, "license_type", license_type)
                and helpers.matches(row, "franchise_state", franchise_state)
                and helpers.matches(row, "state_code", state_code))

    rows, limit, offset, total = helpers.listing("licenses", derive.serialize_license, predicate)
    return envelope.list_response(rows, limit, offset, total)


@bp.get("/state-licenses/<state_license_id>")
def read_license(state_license_id):
    authenticate(ALL_ROLES)
    licence = helpers.find("licenses", state_license_id)
    cascades.refresh_license_expiry(licence)
    return envelope.object_response(derive.serialize_license(licence))


@bp.post("/state-licenses")
def create_license():
    authenticate(["ComplianceOfficer"])
    payload = validation.body()
    state_code = validation.field_state_code(payload, "state_code")
    license_type = validation.field_enum(payload, "license_type", LICENSE_TYPES)
    annual_cap = validation.field_number(payload, "annual_barrel_cap", 2, minimum=0)
    franchise_state = validation.field_bool(payload, "franchise_state")
    effective_from = validation.field_datetime(payload, "effective_from_utc")
    expires_at = validation.field_datetime(payload, "expires_at_utc")
    validation.require_interval("effective_from_utc", effective_from,
                                "expires_at_utc", expires_at)
    notice_days = validation.field_int(payload, "termination_notice_days",
                                       minimum=0, maximum=365,
                                       required=False, default=90)
    helpers.unique("licenses", state_code)
    row = store.new_row({
        "state_code": state_code,
        "license_type": license_type,
        "annual_barrel_cap": calc.bbl2(annual_cap),
        "franchise_state": bool(franchise_state),
        "termination_notice_days": notice_days,
        "effective_from_utc": effective_from,
        "expires_at_utc": expires_at,
        "status": "ACTIVE",
        "carry_in_barrels_ytd": calc.bbl(0),
    })
    helpers.insert("licenses", row)
    return envelope.object_response(derive.serialize_license(row), 201)


@bp.post("/state-licenses/<state_license_id>/ytd-adjustments")
def license_ytd_adjustments(state_license_id):
    authenticate(["ComplianceOfficer"])
    payload = validation.body()
    carry_in = _carry_in_barrels(payload)
    licence = helpers.find("licenses", state_license_id)
    licence["carry_in_barrels_ytd"] = calc.bbl(carry_in)
    store.touch(licence)
    return envelope.object_response(derive.serialize_license(licence))


def _carry_in_barrels(payload):
    for name in ("carry_in_barrels_ytd", "carry_in_bbl", "barrels_ytd"):
        if payload.get(name) is not None:
            return validation.field_number(payload, name, 3, minimum=0)
    validation.bad("Field 'carry_in_barrels_ytd' is required.")


# ---------------------------------------------------------------------------
# distributor appointments
# ---------------------------------------------------------------------------

@bp.get("/distributor-appointments")
def list_appointments():
    authenticate(ALL_ROLES)
    state_license_id = validation.query_string("state_license_id")
    appointed_beer_id = validation.query_string("appointed_beer_id")
    state = validation.query_enum("state", APPOINTMENT_STATES)

    def predicate(row):
        return (helpers.matches(row, "state_license_id", state_license_id)
                and helpers.matches(row, "appointed_beer_id", appointed_beer_id)
                and helpers.matches(row, "state", state))

    rows, limit, offset, total = helpers.listing(
        "appointments", derive.serialize_appointment, predicate)
    return envelope.list_response(rows, limit, offset, total)


@bp.get("/distributor-appointments/<appointment_id>")
def read_appointment(appointment_id):
    authenticate(ALL_ROLES)
    row = helpers.find("appointments", appointment_id)
    return envelope.object_response(derive.serialize_appointment(row))


@bp.post("/distributor-appointments")
def create_appointment():
    user_id, _role = authenticate(["BreweryAdmin"])
    payload = validation.body()
    state_license_id = validation.field_id(payload, "state_license_id")
    distributor_name = validation.field_string(payload, "distributor_name", 1, 120)
    expected_version = validation.field_int(payload, "expected_state_license_version")
    appointed_beer_id = validation.field_id(payload, "appointed_beer_id", required=False)
    good_cause_code = validation.field_enum(payload, "good_cause_code", GOOD_CAUSE_CODES,
                                            required=False)

    licence = helpers.find("licenses", state_license_id)
    if appointed_beer_id is not None:
        helpers.find("beers", appointed_beer_id)
    if expected_version != int(licence.get("version")):
        raise ApiError("ERR_STALE_LICENSE_VERSION")
    cascades.refresh_license_expiry(licence)
    helpers.license_window_guard(licence)

    row = store.new_row({
        "state_license_id": state_license_id,
        "appointed_beer_id": appointed_beer_id,
        "distributor_name": distributor_name,
        "state": "PROPOSED",
        "proposed_by_user_id": user_id,
        "approved_by_user_id": None,
        "activated_at_utc": None,
        "termination_requested_at_utc": None,
        "termination_effective_utc": None,
        "good_cause_code": good_cause_code,
        "terminated_at_utc": None,
    })
    helpers.insert("appointments", row)
    return envelope.object_response(derive.serialize_appointment(row), 201)


@bp.post("/distributor-appointments/<appointment_id>/approve")
def approve_appointment(appointment_id):
    user_id, _role = authenticate(["ComplianceOfficer"])
    validation.body()
    appointment = helpers.find("appointments", appointment_id)
    if appointment.get("state") != "PROPOSED":
        raise ApiError("ERR_APPOINTMENT_TRANSITION_INVALID")
    licence = helpers.find("licenses", appointment["state_license_id"])
    cascades.refresh_license_expiry(licence)
    helpers.license_active_guard(licence)
    if user_id == appointment.get("proposed_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if _scope_conflict(appointment):
        raise ApiError("ERR_DUPLICATE_APPOINTMENT_SCOPE")

    seen = set()
    appointment["state"] = "ACTIVE"
    appointment["approved_by_user_id"] = user_id
    appointment["activated_at_utc"] = helpers.now()
    cascades.touch_once(appointment, seen)
    cascades.touch_once(licence, seen)
    cascades.appointment_activated_cascade(appointment, seen)
    return envelope.object_response(derive.serialize_appointment(appointment))


def _scope_conflict(appointment):
    for other in derive.rows("appointments"):
        if other["id"] == appointment["id"]:
            continue
        if other.get("state_license_id") != appointment["state_license_id"]:
            continue
        if other.get("state") not in LIVE_APPOINTMENT_STATES:
            continue
        mine = appointment.get("appointed_beer_id")
        theirs = other.get("appointed_beer_id")
        if mine is None or theirs is None or mine == theirs:
            return True
    return False


@bp.post("/distributor-appointments/<appointment_id>/termination")
def terminate_appointment(appointment_id):
    authenticate(["ComplianceOfficer"])
    payload = validation.body()
    phase = validation.field_enum(payload, "phase", TERMINATION_PHASES)
    good_cause_code = validation.field_enum(payload, "good_cause_code", GOOD_CAUSE_CODES,
                                            required=False)
    appointment = helpers.find("appointments", appointment_id)
    licence = helpers.find("licenses", appointment["state_license_id"])

    legal = {
        "REQUEST": ("ACTIVE",),
        "FINALIZE": ("TERMINATION_REQUESTED",),
        "WITHDRAW": ("TERMINATION_REQUESTED",),
    }
    if appointment.get("state") not in legal[phase]:
        raise ApiError("ERR_APPOINTMENT_TRANSITION_INVALID")

    seen = set()
    if phase == "REQUEST":
        if licence.get("franchise_state") and good_cause_code is None:
            raise ApiError("ERR_GOOD_CAUSE_REQUIRED")
        requested_at = helpers.now()
        appointment["state"] = "TERMINATION_REQUESTED"
        appointment["termination_requested_at_utc"] = requested_at
        if licence.get("franchise_state"):
            days = int(licence.get("termination_notice_days") or 0)
            appointment["termination_effective_utc"] = requested_at + timedelta(days=days)
        else:
            appointment["termination_effective_utc"] = requested_at
        if good_cause_code is not None:
            appointment["good_cause_code"] = good_cause_code
        cascades.touch_once(appointment, seen)
    elif phase == "WITHDRAW":
        appointment["state"] = "ACTIVE"
        appointment["termination_requested_at_utc"] = None
        appointment["termination_effective_utc"] = None
        appointment["good_cause_code"] = None
        cascades.touch_once(appointment, seen)
    else:
        effective = appointment.get("termination_effective_utc")
        if effective is not None and helpers.now() < effective:
            raise ApiError("ERR_TERMINATION_NOTICE_NOT_ELAPSED")
        appointment["state"] = "TERMINATED"
        appointment["terminated_at_utc"] = helpers.now()
        cascades.touch_once(appointment, seen)
        cascades.touch_once(licence, seen)
    return envelope.object_response(derive.serialize_appointment(appointment))
