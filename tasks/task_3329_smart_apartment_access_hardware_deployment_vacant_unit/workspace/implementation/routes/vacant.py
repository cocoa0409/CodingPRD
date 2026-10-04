"""Vacant-unit automation (PRD 3.3)."""

from calculations import (
    SETPOINT_MAX_C,
    SETPOINT_MIN_C,
    _round,
    vacant_unit_setpoint_c,
)
from db import db, touch
from errors import ERR_SETPOINT_OUT_OF_RANGE, ERR_INVALID_REQUEST, ApiError
from middleware import require_roles
from records import body, require_value, serialize, validate_body
from response import success
from svc_common import active_residents, get_unit, recompute_budget


@require_roles("PropertyManager")
def run_vacant_automation(caller, unitId):
    payload = body()
    validate_body(
        payload,
        required=("window_forecast_c", "relative_humidity_pct"),
        optional=("setpoint_override_c",),
    )
    forecast = require_value(payload, "window_forecast_c")
    humidity = require_value(payload, "relative_humidity_pct")
    unit = get_unit(unitId)

    override = payload.get("setpoint_override_c")
    if override is None:
        setpoint = vacant_unit_setpoint_c(forecast, humidity)
    else:
        if override < SETPOINT_MIN_C or override > SETPOINT_MAX_C:
            raise ApiError(
                ERR_SETPOINT_OUT_OF_RANGE,
                "setpoint_override_c must lie within [%s, %s]"
                % (SETPOINT_MIN_C, SETPOINT_MAX_C),
            )
        setpoint = _round(override, 1)

    unit["target_setpoint_c"] = setpoint
    unit["hvac_mode"] = "VACANT_AUTO"
    # NOTICE_ENDED -> VACANT when no ACTIVE resident still references the unit
    if unit.get("occupancy_status") == "NOTICE_ENDED" and not active_residents(unit["id"]):
        unit["occupancy_status"] = "VACANT"
        unit["_notice_end_at"] = None
    touch(unit)
    recompute_budget(unit.get("property_id"))
    return success(serialize(unit), "object", 200)


API_ROUTES = [
    ("POST", "/units/<unitId>/vacant-automation", run_vacant_automation),
]