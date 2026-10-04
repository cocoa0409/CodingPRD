"""StormEvent endpoints: open, read, OCC-guarded reading updates, dissipate."""
from flask import Blueprint

from auth import authenticate, check_office_scope, require_role
from constants import HAZARD_TYPES
from db import STORE, now
from errors import api_error
from serialize import serialize
from util import as_int, as_number, base_entity, envelope, get_body, touch

bp = Blueprint("storms", __name__, url_prefix="/alerts")

FORECASTING = ["Forecaster", "MeteorologistInCharge"]
ANY_ROLE = ["PlatformAdmin", "Forecaster", "MeteorologistInCharge", "VerificationAnalyst", "EmergencyManager"]

READING_INT_FIELDS = ("max_wind_mph", "motion_degrees", "speed_kt")
READING_NUM_FIELDS = ("max_hail_inches", "rainfall_rate_in_hr")
READING_BOOL_FIELDS = ("rotation_couplet", "debris_signature")


def _get_storm_or_404(storm_id):
    storm = STORE["storms"].get(storm_id)
    if storm is None:
        raise api_error("ERR_STORM_EVENT_NOT_FOUND", "StormEvent %s does not exist." % storm_id)
    return storm


@bp.post("/storm-events")
def create_storm():
    role, _uid, forecaster = authenticate()
    require_role(role, FORECASTING)
    body = get_body()
    office_id = body.get("office_id")
    hazard_type = body.get("hazard_type")
    # tier 3 (scope) is evaluated on the raw body value before FK existence
    if isinstance(office_id, str) and office_id:
        check_office_scope(forecaster, office_id)
    # tier 4: schema
    if not isinstance(office_id, str) or not office_id:
        raise api_error("ERR_INVALID_REQUEST", "office_id is required.")
    if hazard_type not in HAZARD_TYPES:
        raise api_error("ERR_INVALID_REQUEST", "hazard_type must be one of %s" % HAZARD_TYPES)
    readings = {}
    for field in READING_INT_FIELDS:
        if field in body:
            value = as_int(body.get(field))
            if value is None:
                raise api_error("ERR_INVALID_REQUEST", "%s must be an integer." % field)
            readings[field] = value
    for field in READING_NUM_FIELDS:
        if field in body:
            value = as_number(body.get(field))
            if value is None:
                raise api_error("ERR_INVALID_REQUEST", "%s must be a number." % field)
            readings[field] = value
    for field in READING_BOOL_FIELDS:
        if field in body:
            value = body.get(field)
            if not isinstance(value, bool):
                raise api_error("ERR_INVALID_REQUEST", "%s must be a boolean." % field)
            readings[field] = value
    # tier 5: office FK existence
    if STORE["offices"].get(office_id) is None:
        raise api_error("ERR_OFFICE_NOT_FOUND", "ForecastOffice %s does not exist." % office_id)
    storm = base_entity()
    storm.update({
        "office_id": office_id,
        "hazard_type": hazard_type,
        "max_wind_mph": readings.get("max_wind_mph", 0),
        "max_hail_inches": readings.get("max_hail_inches", 0),
        "rainfall_rate_in_hr": readings.get("rainfall_rate_in_hr", 0),
        "rotation_couplet": readings.get("rotation_couplet", False),
        "debris_signature": readings.get("debris_signature", False),
        "motion_degrees": readings.get("motion_degrees", 0),
        "speed_kt": readings.get("speed_kt", 0),
        "detected_at": now(),
        "status": "DETECTED",
        "dissipated_at": None,
    })
    STORE["storms"][storm["id"]] = storm
    return envelope(serialize(storm), "object", 201)


@bp.get("/storm-events/<storm_id>")
def get_storm(storm_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    return envelope(serialize(_get_storm_or_404(storm_id)), "object", 200)


@bp.put("/storm-events/<storm_id>")
def update_storm(storm_id):
    role, _uid, forecaster = authenticate()
    require_role(role, FORECASTING)
    body = get_body()
    # tier 4: schema — expected_storm_event_version is a required OCC field
    expected = as_int(body.get("expected_storm_event_version"))
    if expected is None:
        raise api_error(
            "ERR_INVALID_REQUEST", "expected_storm_event_version is required and must be an integer."
        )
    updates = {}
    for field in READING_INT_FIELDS:
        if field in body:
            value = as_int(body.get(field))
            if value is None:
                raise api_error("ERR_INVALID_REQUEST", "%s must be an integer." % field)
            updates[field] = value
    for field in READING_NUM_FIELDS:
        if field in body:
            value = as_number(body.get(field))
            if value is None:
                raise api_error("ERR_INVALID_REQUEST", "%s must be a number." % field)
            updates[field] = value
    for field in READING_BOOL_FIELDS:
        if field in body:
            value = body.get(field)
            if not isinstance(value, bool):
                raise api_error("ERR_INVALID_REQUEST", "%s must be a boolean." % field)
            updates[field] = value
    # tier 5: path existence
    storm = _get_storm_or_404(storm_id)
    # tier 3: office scope against the loaded entity
    check_office_scope(forecaster, storm["office_id"])
    # tier 6: OCC
    if expected != storm["version"]:
        raise api_error("ERR_STALE_VERSION", "expected_storm_event_version does not match the stored version.")
    # tier 7: no update transition leaves DISSIPATED
    if storm["status"] == "DISSIPATED":
        raise api_error("ERR_INVALID_STORM_STATE", "A DISSIPATED storm cannot be updated.")
    storm.update(updates)
    if storm["status"] == "DETECTED":
        storm["status"] = "TRACKING"  # first successful update flips DETECTED -> TRACKING
    touch(storm)
    return envelope(serialize(storm), "object", 200)


@bp.post("/storm-events/<storm_id>/dissipate")
def dissipate_storm(storm_id):
    role, _uid, forecaster = authenticate()
    require_role(role, FORECASTING)
    storm = _get_storm_or_404(storm_id)
    check_office_scope(forecaster, storm["office_id"])
    if storm["status"] not in ("DETECTED", "TRACKING"):
        raise api_error("ERR_INVALID_STORM_STATE", "Only a DETECTED or TRACKING storm can dissipate.")
    storm["status"] = "DISSIPATED"
    storm["dissipated_at"] = now()
    touch(storm)
    return envelope(serialize(storm), "object", 200)
