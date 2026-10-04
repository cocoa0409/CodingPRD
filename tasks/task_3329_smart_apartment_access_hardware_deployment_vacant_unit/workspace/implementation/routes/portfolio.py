"""Property, Building and Unit endpoints (PRD 3.1)."""

from flask import request

from calculations import DEFAULT_VACANT_SETPOINT_C, _round, refresh_connectivity
from db import db, iso, parse_instant, touch
from errors import ERR_DUPLICATE_UNIT_NUMBER, ERR_INVALID_REQUEST, ApiError
from middleware import require_roles
from records import body, require_value, serialize, validate_body
from response import paged, success
from svc_common import get_building, get_property, get_unit, new_record

NETWORK_DESIGNS = ("POINT_TO_POINT", "FIELD_MESH", "HUB_RELAY")


def _instant_or_none(value):
    if value is None:
        return None
    return iso(parse_instant(value, "instant"))


def _validate_network_design(value):
    if value not in NETWORK_DESIGNS:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "network_design must be one of %s" % ", ".join(NETWORK_DESIGNS),
        )
    return value


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------
@require_roles("PlatformAdmin")
def create_property(caller):
    payload = body()
    validate_body(
        payload,
        required=("name", "address_line"),
        optional=("unit_capacity", "temp_budget_cents_per_day"),
    )
    record = new_record(
        {
            "name": require_value(payload, "name"),
            "address_line": require_value(payload, "address_line"),
            "unit_capacity": payload.get("unit_capacity") or 0,
            "temp_budget_cents_per_day": (
                payload.get("temp_budget_cents_per_day")
                if payload.get("temp_budget_cents_per_day") is not None
                else 500
            ),
            "budget_committed_cents": 0,
        }
    )
    db.properties[record["id"]] = record
    return success(serialize(record), "object", 201)


@require_roles("PlatformAdmin", "PropertyManager")
def get_property_by_id(caller, propertyId):
    return success(serialize(get_property(propertyId)), "object", 200)


# ---------------------------------------------------------------------------
# Buildings
# ---------------------------------------------------------------------------
@require_roles("PlatformAdmin")
def create_building(caller, propertyId):
    prop = get_property(propertyId)
    payload = body()
    validate_body(
        payload,
        required=("name", "network_design", "wifi_rssi_dbm"),
        optional=("last_hub_service_at",),
    )
    rssi = payload.get("wifi_rssi_dbm")
    if rssi is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: wifi_rssi_dbm")
    record = new_record(
        {
            "property_id": prop["id"],
            "name": require_value(payload, "name"),
            "network_design": _validate_network_design(
                require_value(payload, "network_design")
            ),
            "wifi_rssi_dbm": rssi,
            "last_hub_service_at": _instant_or_none(payload.get("last_hub_service_at")),
            "connectivity_ok": False,
        }
    )
    db.buildings[record["id"]] = record
    refresh_connectivity(record)
    return success(serialize(record), "object", 201)


@require_roles("PlatformAdmin", "PropertyManager", "HardwareTechnician")
def list_buildings(caller):
    rows = list(db.buildings.values())
    property_id = request.args.get("property_id")
    if property_id:
        rows = [row for row in rows if row.get("property_id") == property_id]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
@require_roles("PlatformAdmin", "PropertyManager")
def create_unit(caller, propertyId):
    prop = get_property(propertyId)
    payload = body()
    validate_body(
        payload,
        required=("unit_number",),
        optional=("building_id", "pod_entry_window_start", "pod_entry_window_end"),
    )
    unit_number = require_value(payload, "unit_number")
    for existing in db.units.values():
        if (
            existing.get("property_id") == prop["id"]
            and existing.get("unit_number") == unit_number
        ):
            raise ApiError(
                ERR_DUPLICATE_UNIT_NUMBER,
                "Unit number %s already exists in this property" % unit_number,
            )
    building_id = payload.get("building_id")
    if building_id is not None:
        get_building(building_id)
    record = new_record(
        {
            "property_id": prop["id"],
            "building_id": building_id,
            "unit_number": unit_number,
            "occupancy_status": "VACANT",
            "target_setpoint_c": _round(DEFAULT_VACANT_SETPOINT_C, 1),
            "hvac_mode": "VACANT_AUTO",
            "pod_entry_window_start": _instant_or_none(
                payload.get("pod_entry_window_start")
            ),
            "pod_entry_window_end": _instant_or_none(payload.get("pod_entry_window_end")),
            "unauthorized_entry_detected": False,
            "_notice_end_at": None,
        }
    )
    db.units[record["id"]] = record
    return success(serialize(record), "object", 201)


@require_roles(
    "PlatformAdmin", "PropertyManager", "HardwareTechnician", "LeasingAgent"
)
def list_units(caller):
    rows = list(db.units.values())
    property_id = request.args.get("property_id")
    building_id = request.args.get("building_id")
    occupancy = request.args.get("occupancy_status")
    if property_id:
        rows = [row for row in rows if row.get("property_id") == property_id]
    if building_id:
        rows = [row for row in rows if row.get("building_id") == building_id]
    if occupancy:
        rows = [row for row in rows if row.get("occupancy_status") == occupancy]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


@require_roles(
    "PlatformAdmin", "PropertyManager", "HardwareTechnician", "LeasingAgent"
)
def get_unit_by_id(caller, unitId):
    return success(serialize(get_unit(unitId)), "object", 200)


API_ROUTES = [
    ("POST", "/properties", create_property),
    ("GET", "/properties/<propertyId>", get_property_by_id),
    ("POST", "/properties/<propertyId>/buildings", create_building),
    ("GET", "/buildings", list_buildings),
    ("POST", "/properties/<propertyId>/units", create_unit),
    ("GET", "/units", list_units),
    ("GET", "/units/<unitId>", get_unit_by_id),
]