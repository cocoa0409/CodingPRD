"""Emergency event endpoints (PRD 3.8)."""
from flask import Blueprint

import auth
import config
import engine
import envelope
import serialize
import store
import validate
from errors import ApiError, not_found
from routes.helpers import filter_eq, list_result

bp = Blueprint("emergencies", __name__)

_LEGAL_ADVANCES = {
    "DETECTED": ("RESPONDING",),
    "RESPONDING": ("EVACUATION_ORDERED", "CONTAINED"),
    "EVACUATION_ORDERED": ("CONTAINED",),
    "CONTAINED": ("CLOSED",),
    "CLOSED": (),
}

EMERGENCY_ROLES = [config.ROLE_FIELD_OPERATOR, config.ROLE_COMPLIANCE_OFFICER]


@bp.post("/emergency-events")
def create_event():
    auth.require(EMERGENCY_ROLES)
    body = validate.json_body()

    field_id = validate.field_id(body, "storage_field_id")
    event_type = validate.field_enum(body, "event_type", config.EVENT_TYPES)
    severity = validate.field_enum(body, "severity", config.SEVERITIES)
    detected_at = validate.field_instant(body, "detected_at")
    well_id = validate.field_id(body, "well_id", required=False)

    field = validate.resolve_body_fk("StorageField", field_id)
    well = None
    if well_id is not None:
        well = validate.resolve_body_fk("Well", well_id)
        if well["storage_field_id"] != field["id"]:
            raise not_found("Well", "this wellbore is not on the supplied reservoir.")

    event = store.new_record()
    event.update({
        "storage_field_id": field["id"],
        "well_id": well["id"] if well is not None else None,
        "event_type": event_type,
        "severity": severity,
        "detected_at": detected_at,
        "status": "DETECTED",
        "evacuation_radius_m": 0,
        "responder_notes": None,
        "contained_at": None,
        "closed_at": None,
    })
    store.put("EmergencyEvent", event)
    return envelope.created(serialize.emergency_event(event))


@bp.get("/emergency-events")
def list_events():
    auth.require(config.STAFF_ROLES)
    limit, offset = validate.pagination()
    field_id = validate.query_id("storage_field_id")
    well_id = validate.query_id("well_id")
    status = validate.query_enum("status", config.EMERGENCY_STATUSES)
    severity = validate.query_enum("severity", config.SEVERITIES)

    rows = store.values("EmergencyEvent")
    rows = filter_eq(rows, "storage_field_id", field_id)
    rows = filter_eq(rows, "well_id", well_id)
    rows = filter_eq(rows, "status", status)
    rows = filter_eq(rows, "severity", severity)
    return list_result(rows, serialize.emergency_event, limit, offset)


@bp.get("/emergency-events/<event_id>")
def read_event(event_id):
    auth.require(config.STAFF_ROLES)
    event = validate.resolve_path("EmergencyEvent", event_id)
    return envelope.object_response(serialize.emergency_event(event))


@bp.post("/emergency-events/<event_id>/advance")
def advance_event(event_id):
    auth.require(EMERGENCY_ROLES)
    body = validate.json_body()
    to_status = validate.field_enum(body, "to_status", config.EMERGENCY_STATUSES)
    responder_notes = validate.field_str(body, "responder_notes", required=False)
    radius = validate.field_int(body, "evacuation_radius_m", required=False)
    event = validate.resolve_path("EmergencyEvent", event_id)

    if to_status not in _LEGAL_ADVANCES[event["status"]]:
        raise ApiError("ERR_INVALID_EMERGENCY_STATE",
                       "an event in %s may not advance to %s." % (event["status"], to_status))

    field = store.storage_fields[event["storage_field_id"]]

    if to_status == "EVACUATION_ORDERED":
        if event["severity"] not in ("SERIOUS", "CRITICAL"):
            raise ApiError("ERR_EVACUATION_RADIUS_INVALID",
                           "only a SERIOUS or CRITICAL event may order an evacuation.")
        if (radius is None or radius < config.MIN_EVACUATION_RADIUS_M
                or radius > config.MAX_EVACUATION_RADIUS_M):
            raise ApiError("ERR_EVACUATION_RADIUS_INVALID",
                           "evacuation_radius_m must lie between %d and %d metres."
                           % (config.MIN_EVACUATION_RADIUS_M, config.MAX_EVACUATION_RADIUS_M))
    if to_status == "CLOSED":
        # The closure gate is declared on the edge itself, so it answers at rung 7.
        for program in store.programs_of_field(field["id"]):
            if program["status"] == "ESCALATED":
                raise ApiError("ERR_INVALID_EMERGENCY_STATE",
                               "an escalated remediation program remains on this field.")

    event["status"] = to_status
    if responder_notes is not None:
        event["responder_notes"] = responder_notes
    if to_status == "EVACUATION_ORDERED":
        event["evacuation_radius_m"] = radius
    if to_status == "CONTAINED":
        event["contained_at"] = store.now()
    if to_status == "CLOSED":
        event["closed_at"] = store.now()
    store.touch(event)

    if to_status == "RESPONDING":
        engine.refresh_field(field)
        engine.phase_a_posture(field, "FROZEN", "emergency response %s" % engine.today_str())
    elif to_status == "EVACUATION_ORDERED":
        for program in store.sorted_rows(store.programs_of_field(field["id"])):
            if program["status"] == "OPEN":
                program["status"] = "ESCALATED"
                store.touch(program)
        for unit in store.sorted_rows(store.units_of_field(field["id"])):
            for run in store.sorted_rows(store.runs_of_unit(unit["id"])):
                if run["status"] == "SCHEDULED":
                    run["status"] = "CANCELLED"
                    store.touch(run)
                    unit["scheduled_run_count"] = int(unit["scheduled_run_count"]) - 1
            unit["status"] = "OUT_OF_SERVICE"
            store.touch(unit)
        engine.refresh_field(field)
    else:
        engine.refresh_field(field)
    return envelope.object_response(serialize.emergency_event(event))
