"""Wellbore, mechanical integrity test and remediation program endpoints (PRD 3.1, 3.2)."""
from flask import Blueprint

import auth
import config
import engine
import envelope
import serialize
import store
import validate
from errors import ApiError
from routes.helpers import filter_eq, list_result
from utils import add_days

bp = Blueprint("wells", __name__)


# ================================================================ wellbores
@bp.post("/wells")
def create_well():
    auth.require([config.ROLE_FIELD_OPERATOR])
    body = validate.json_body()

    field_id = validate.field_id(body, "storage_field_id")
    well_name = validate.field_str(body, "well_name", allow_empty=False)
    well_type = validate.field_enum(body, "well_type", config.WELL_TYPES)
    rated_rate = validate.field_int(body, "rated_rate_dth_per_day", minimum=0)
    last_mit_passed_at = validate.field_instant(body, "last_mit_passed_at")
    casing_pressure = validate.field_int(body, "casing_pressure_psig", required=False, default=0)
    initial_state = validate.field_enum(body, "initial_operational_state",
                                        config.OPERATIONAL_STATES, required=False,
                                        default="IN_SERVICE")

    field = validate.resolve_body_fk("StorageField", field_id)

    mit_due_at = add_days(last_mit_passed_at, config.MIT_INTERVAL_DAYS)
    well = store.new_record()
    well.update({
        "storage_field_id": field["id"],
        "well_name": well_name,
        "well_type": well_type,
        "rated_rate_dth_per_day": rated_rate,
        "casing_pressure_psig": casing_pressure,
        "last_mit_passed_at": last_mit_passed_at,
        "mit_due_at": mit_due_at,
        "operational_state": initial_state,
        "integrity_state": "MIT_DUE" if mit_due_at <= store.now() else "MIT_CURRENT",
        "shut_in_reason": None,
        "service_change_count": 0,
    })
    store.put("Well", well)
    engine.refresh_field(field)
    return envelope.created(serialize.well(well))


@bp.get("/wells")
def list_wells():
    auth.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    field_id = validate.query_id("storage_field_id")
    operational_state = validate.query_enum("operational_state", config.OPERATIONAL_STATES)
    integrity_state = validate.query_enum("integrity_state", config.INTEGRITY_STATES)

    rows = store.values("Well")
    rows = filter_eq(rows, "storage_field_id", field_id)
    rows = filter_eq(rows, "operational_state", operational_state)
    rows = filter_eq(rows, "integrity_state", integrity_state)
    return list_result(rows, serialize.well, limit, offset)


@bp.get("/wells/<well_id>")
def read_well(well_id):
    auth.require(config.ALL_ROLES)
    well = validate.resolve_path("Well", well_id)
    return envelope.object_response(serialize.well(well))


def _has_open_program(well_id):
    return any(p["status"] in ("OPEN", "ESCALATED") for p in store.programs_of_well(well_id))


@bp.post("/wells/<well_id>/service-change")
def service_change(well_id):
    auth.require([config.ROLE_FIELD_OPERATOR])
    body = validate.json_body()
    target = validate.field_enum(body, "to_operational_state", config.OPERATIONAL_STATES)
    validate.field_str(body, "reason", required=False)
    well = validate.resolve_path("Well", well_id)

    current = well["operational_state"]
    if target == "IN_SERVICE":
        legal = (current == "SHUT_IN" and well["integrity_state"] != "MIT_FAILED"
                 and not _has_open_program(well["id"]))
    elif target == "SHUT_IN":
        legal = current == "IN_SERVICE" and not any(
            t["status"] == "PENDING" for t in store.tickets_of_well(well["id"]))
    else:
        legal = current == "SHUT_IN" and not any(
            m["status"] == "SCHEDULED" for m in store.mits_of_well(well["id"]))
    if not legal:
        raise ApiError("ERR_INVALID_WELL_STATE",
                       "A wellbore in %s may not move to %s." % (current, target))

    well["operational_state"] = target
    if target == "SHUT_IN":
        well["shut_in_reason"] = "OPERATOR_REQUEST"
    elif target == "IN_SERVICE":
        well["shut_in_reason"] = None
    well["service_change_count"] = int(well["service_change_count"]) + 1
    store.touch(well)

    field = store.storage_fields[well["storage_field_id"]]
    before, after = engine.refresh_field(field)
    engine.run_sweeps(field, before, after, "well service change %s" % engine.today_str())
    return envelope.object_response(serialize.well(well))


# ================================================================ integrity tests
@bp.post("/mechanical-integrity-tests")
def create_mit():
    auth.require([config.ROLE_INTEGRITY_ENGINEER])
    body = validate.json_body()

    well_id = validate.field_id(body, "well_id")
    test_type = validate.field_enum(body, "test_type", config.MIT_TEST_TYPES)
    start = validate.field_instant(body, "scheduled_start_at")
    end = validate.field_instant(body, "scheduled_end_at")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "scheduled_end_at must be strictly after scheduled_start_at.")

    well = validate.resolve_body_fk("Well", well_id)

    if start < store.now():
        raise ApiError("ERR_MIT_WINDOW_IN_PAST",
                       "scheduled_start_at may not begin before the current clock.")
    if engine.mit_window_conflict(well["id"], start, end):
        raise ApiError("ERR_MIT_WINDOW_CONFLICT",
                       "another scheduled test occupies this wellbore window.")

    test = store.new_record()
    test.update({
        "well_id": well["id"],
        "test_type": test_type,
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "status": "SCHEDULED",
        "outcome": None,
        "result_pressure_psig": None,
        "recorded_by_user_id": None,
        "recorded_at": None,
    })
    store.put("MechanicalIntegrityTest", test)
    return envelope.created(serialize.mit(test))


@bp.get("/mechanical-integrity-tests")
def list_mits():
    auth.require(config.STAFF_ROLES)
    limit, offset = validate.pagination()
    well_id = validate.query_id("well_id")
    status = validate.query_enum("status", config.MIT_STATUSES)

    rows = store.values("MechanicalIntegrityTest")
    rows = filter_eq(rows, "well_id", well_id)
    rows = filter_eq(rows, "status", status)
    return list_result(rows, serialize.mit, limit, offset)


@bp.get("/mechanical-integrity-tests/<mit_id>")
def read_mit(mit_id):
    auth.require(config.STAFF_ROLES)
    test = validate.resolve_path("MechanicalIntegrityTest", mit_id)
    return envelope.object_response(serialize.mit(test))


@bp.post("/mechanical-integrity-tests/<mit_id>/record-result")
def record_result(mit_id):
    user_id, _role = auth.require([config.ROLE_INTEGRITY_ENGINEER])
    body = validate.json_body()
    outcome = validate.field_enum(body, "outcome", config.MIT_OUTCOMES)
    result_pressure = validate.field_int(body, "result_pressure_psig")
    test = validate.resolve_path("MechanicalIntegrityTest", mit_id)

    if test["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_MIT_STATE",
                       "only a SCHEDULED test may take a result.")
    well = store.wells[test["well_id"]]
    field = store.storage_fields[well["storage_field_id"]]
    if result_pressure > int(field["max_pressure_psig"]):
        raise ApiError("ERR_FIELD_PRESSURE_LIMIT",
                       "result_pressure_psig exceeds the field's max_pressure_psig.")
    if store.now() < test["scheduled_end_at"]:
        raise ApiError("ERR_MIT_WINDOW_NOT_ELAPSED",
                       "the test window has not yet elapsed.")

    recorded_at = store.now()
    test["outcome"] = outcome
    test["result_pressure_psig"] = result_pressure
    test["recorded_by_user_id"] = user_id
    test["recorded_at"] = recorded_at
    test["status"] = "PASSED" if outcome == "PASS" else "FAILED"
    store.touch(test)

    if outcome == "PASS":
        well["integrity_state"] = "MIT_CURRENT"
        well["last_mit_passed_at"] = recorded_at
        well["mit_due_at"] = add_days(recorded_at, config.MIT_INTERVAL_DAYS)
        well["casing_pressure_psig"] = result_pressure
        store.touch(well)
        engine.refresh_field(field)
    elif outcome == "FAIL":
        well["integrity_state"] = "MIT_FAILED"
        well["operational_state"] = "SHUT_IN"
        well["shut_in_reason"] = "MIT_FAILURE"
        store.touch(well)
        program = store.new_record()
        program.update({
            "well_id": well["id"],
            "triggering_mit_id": test["id"],
            "status": "OPEN",
            "opened_at": recorded_at,
            "due_at": add_days(recorded_at, config.REMEDIATION_DUE_DAYS),
            "verification_notes": None,
            "completed_by_user_id": None,
            "completed_at": None,
        })
        store.put("RemediationProgram", program)
        engine.refresh_field(field)
        engine.phase_a_posture(field, field["field_posture"],
                               "integrity test failure %s" % engine.today_str())
    else:
        engine.refresh_field(field)
    return envelope.object_response(serialize.mit(test))


# ================================================================ remediation programs
@bp.get("/remediation-programs")
def list_programs():
    auth.require(config.STAFF_ROLES)
    limit, offset = validate.pagination()
    well_id = validate.query_id("well_id")
    triggering_mit_id = validate.query_id("triggering_mit_id")
    status = validate.query_enum("status", config.REMEDIATION_STATUSES)

    rows = store.values("RemediationProgram")
    rows = filter_eq(rows, "well_id", well_id)
    rows = filter_eq(rows, "triggering_mit_id", triggering_mit_id)
    rows = filter_eq(rows, "status", status)
    return list_result(rows, serialize.remediation_program, limit, offset)


@bp.get("/remediation-programs/<program_id>")
def read_program(program_id):
    auth.require(config.STAFF_ROLES)
    program = validate.resolve_path("RemediationProgram", program_id)
    return envelope.object_response(serialize.remediation_program(program))


@bp.post("/remediation-programs/<program_id>/complete")
def complete_program(program_id):
    user_id, _role = auth.require([config.ROLE_INTEGRITY_ENGINEER])
    body = validate.json_body()
    notes = validate.field_str(body, "verification_notes")
    program = validate.resolve_path("RemediationProgram", program_id)

    if program["status"] != "OPEN":
        raise ApiError("ERR_INVALID_REMEDIATION_STATE",
                       "only an OPEN remediation program may be completed.")
    test = store.mits.get(program["triggering_mit_id"])
    if test is not None and test["recorded_by_user_id"] == user_id:
        raise ApiError("ERR_SOD_REMEDIATION_SELF_VERIFICATION",
                       "the engineer who recorded the failure may not verify it.")
    well = store.wells[program["well_id"]]
    field = store.storage_fields[well["storage_field_id"]]
    for event in store.events_of_field(field["id"]):
        if event["status"] in ("RESPONDING", "EVACUATION_ORDERED"):
            raise ApiError("ERR_REMEDIATION_ESCALATED",
                           "an emergency response is under way on this field.")

    program["status"] = "COMPLETED"
    program["completed_by_user_id"] = user_id
    program["completed_at"] = store.now()
    program["verification_notes"] = notes
    store.touch(program)

    well["integrity_state"] = "REMEDIATED"
    well["shut_in_reason"] = None
    store.touch(well)
    engine.refresh_field(field)
    return envelope.object_response(serialize.remediation_program(program))
