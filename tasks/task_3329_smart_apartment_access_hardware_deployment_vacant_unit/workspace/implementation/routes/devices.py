"""Device provisioning, battery replacement, lock events and scans (PRD 3.2, 3.9)."""

from flask import request

from calculations import (
    BATTERY_DRAIN_PER_SCAN,
    LOW_BATTERY_ALERT_PCT,
    device_battery_health_score,
)
from db import clock, db, iso, parse_instant, touch
from errors import (
    ERR_DEVICE_UNREACHABLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ApiError,
)
from middleware import require_roles
from records import body, require_value, serialize, validate_body
from response import paged, success
from svc_common import (
    covering_credential,
    get_building,
    get_device,
    get_unit,
    maintenance_occupations,
    new_record,
)

DEVICE_TYPES = (
    "SMART_LOCK",
    "THERMOSTAT",
    "LEAK_SENSOR",
    "COMMUNITY_ACCESS",
    "HUB",
)
FIRMWARE_VERSIONS = ("LATEST", "OLD", "CRITICAL")


def _validate_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field %s must be one of %s" % (field, ", ".join(allowed)),
        )
    return value


def _raise_alert(building_id, device, alert_type, severity):
    alert = new_record(
        {
            "building_id": building_id,
            "device_id": device["id"],
            "alert_type": alert_type,
            "status": "OPEN",
            "severity": severity,
        }
    )
    db.device_alerts[alert["id"]] = alert
    return alert


def _resolve_open_alerts(device_id, alert_types):
    resolved = []
    for alert in db.device_alerts.values():
        if alert.get("device_id") != device_id:
            continue
        if alert.get("status") == "RESOLVED":
            continue
        if alert.get("alert_type") not in alert_types:
            continue
        alert["status"] = "RESOLVED"
        touch(alert)
        resolved.append(alert)
    return resolved


def _open_alert_count(device_id):
    return len(
        [
            a
            for a in db.device_alerts.values()
            if a.get("device_id") == device_id and a.get("status") == "OPEN"
        ]
    )


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------
@require_roles("PlatformAdmin", "HardwareTechnician")
def create_device(caller):
    payload = body()
    validate_body(
        payload,
        required=("device_type", "building_id", "firmware_version"),
        optional=("unit_id", "battery_pct"),
    )
    device_type = _validate_enum(
        require_value(payload, "device_type"), DEVICE_TYPES, "device_type"
    )
    firmware = _validate_enum(
        require_value(payload, "firmware_version"), FIRMWARE_VERSIONS, "firmware_version"
    )
    building = get_building(require_value(payload, "building_id"))
    unit_id = payload.get("unit_id")
    if unit_id is not None:
        get_unit(unit_id)
    battery = payload.get("battery_pct")
    if device_type == "HUB":
        battery = 100
    elif battery is None:
        battery = 100
    record = new_record(
        {
            "unit_id": unit_id,
            "building_id": building["id"],
            "device_type": device_type,
            "firmware_version": firmware,
            "battery_pct": battery,
            "status": "PROVISIONED",
            "lock_state": "LOCKED",
            "battery_replacements": 0,
            "battery_health_score": None,
        }
    )
    db.devices[record["id"]] = record
    return success(serialize(record), "object", 201)


@require_roles("PlatformAdmin", "PropertyManager", "HardwareTechnician")
def list_devices(caller):
    rows = list(db.devices.values())
    unit_id = request.args.get("unit_id")
    building_id = request.args.get("building_id")
    if unit_id:
        rows = [row for row in rows if row.get("unit_id") == unit_id]
    if building_id:
        rows = [row for row in rows if row.get("building_id") == building_id]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Battery replacement
# ---------------------------------------------------------------------------
@require_roles("HardwareTechnician")
def replace_battery(caller, deviceId):
    payload = body()
    validate_body(payload)
    device = get_device(deviceId)
    if device.get("firmware_version") == "CRITICAL":
        if device.get("status") != "ONLINE":
            raise ApiError(
                ERR_DEVICE_UNREACHABLE, "Device is not reachable for service"
            )
        device["status"] = "DECOMMISSIONED"
        device["battery_pct"] = 100
        device["battery_replacements"] = device.get("battery_replacements", 0) + 1
        touch(device)
        return success(serialize(device), "object", 200)
    if device.get("status") != "ONLINE":
        raise ApiError(ERR_DEVICE_UNREACHABLE, "Device is not reachable for service")
    device["battery_pct"] = 100
    device["battery_replacements"] = device.get("battery_replacements", 0) + 1
    touch(device)
    _resolve_open_alerts(device["id"], ("LOW_BATTERY",))
    return success(serialize(device), "object", 200)


# ---------------------------------------------------------------------------
# Lock events
# ---------------------------------------------------------------------------
def _authorized_open(unit, moment):
    if covering_credential(unit["id"], moment):
        return True
    for visit in db.maintenance_visits.values():
        if visit.get("unit_id") != unit["id"]:
            continue
        if visit.get("status") != "NOTICE_CERTIFIED":
            continue
        start = parse_instant(visit.get("start_at"), "start_at")
        end = parse_instant(visit.get("end_at"), "end_at")
        if start <= moment <= end:
            return True
    return False


@require_roles("HardwareTechnician", "PropertyManager")
def create_lock_event(caller, deviceId):
    payload = body()
    validate_body(
        payload, required=("event_type",), optional=("credential_code",)
    )
    event_type = require_value(payload, "event_type")
    # PRD 3.2: "moves `lock_state` to `UNLOCKED` when the event type is an unlock
    # and back to `LOCKED` on a close". The unlock is carried as `unlock`/`UNLOCK`
    # and the close as `close`/`CLOSE`; both spellings are accepted so neither
    # reading of the prose is disadvantaged.
    _unlock_names = ("UNLOCK", "unlock", "UNLOCKED", "unlocked")
    _close_names = ("CLOSE", "close", "CLOSED", "closed", "LOCK", "lock", "LOCKED", "locked")
    if event_type in _unlock_names:
        unlocked = True
    elif event_type in _close_names:
        unlocked = False
    else:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "event_type must be an unlock (UNLOCK) or a close (CLOSE)",
        )
    device = get_device(deviceId)
    if device.get("device_type") != "SMART_LOCK" or device.get("status") != "ONLINE":
        raise ApiError(
            ERR_INVALID_STATE,
            "Lock events require a SMART_LOCK device that is ONLINE",
        )
    device["lock_state"] = "UNLOCKED" if unlocked else "LOCKED"
    touch(device)
    unit_id = device.get("unit_id")
    if unlocked and unit_id:
        unit = db.units.get(unit_id)
        if unit is not None and unit.get("occupancy_status") == "VACANT":
            if not _authorized_open(unit, clock.now):
                unit["unauthorized_entry_detected"] = True
                touch(unit)
                _raise_alert(device["building_id"], device, "UNAUTHORIZED_ENTRY", "HIGH")
    return success(serialize(device), "object", 200)


# ---------------------------------------------------------------------------
# Reachability scans
# ---------------------------------------------------------------------------
@require_roles("PlatformAdmin", "HardwareTechnician")
def create_device_scan(caller, buildingId):
    building = get_building(buildingId)
    payload = body()
    validate_body(
        payload,
        required=("reachable_device_ids",),
        optional=("window_forecast_c", "relative_humidity_pct"),
    )
    reachable = payload.get("reachable_device_ids")
    if not isinstance(reachable, list):
        raise ApiError(ERR_INVALID_REQUEST, "reachable_device_ids must be an array")
    reachable_set = set(reachable)
    touched = []
    devices = [
        d for d in db.devices.values() if d.get("building_id") == building["id"]
    ]
    for device in devices:
        if device.get("status") == "DECOMMISSIONED":
            continue
        present = device["id"] in reachable_set
        if present:
            if device.get("status") in ("PROVISIONED", "UNREACHABLE"):
                device["status"] = "ONLINE"
                touch(device)
            resolved = _resolve_open_alerts(device["id"], ("OFFLINE", "LOW_BATTERY"))
            touched.extend(resolved)
            if device.get("device_type") != "HUB" and int(
                device.get("battery_pct", 0)
            ) < LOW_BATTERY_ALERT_PCT:
                existing = [
                    a
                    for a in db.device_alerts.values()
                    if a.get("device_id") == device["id"]
                    and a.get("alert_type") == "LOW_BATTERY"
                    and a.get("status") == "OPEN"
                ]
                if not existing:
                    touched.append(
                        _raise_alert(
                            building["id"], device, "LOW_BATTERY", "MEDIUM"
                        )
                    )
        else:
            if device.get("device_type") != "HUB":
                device["battery_pct"] = max(
                    0, int(device.get("battery_pct", 0)) - BATTERY_DRAIN_PER_SCAN
                )
            if device.get("status") == "ONLINE":
                device["status"] = "UNREACHABLE"
                touch(device)
                touched.append(
                    _raise_alert(building["id"], device, "OFFLINE", "HIGH")
                )
            elif device.get("status") == "PROVISIONED":
                touch(device)
    # resolved alerts may recur when their device is absent from the scan
    for alert in db.device_alerts.values():
        if alert.get("building_id") != building["id"]:
            continue
        if alert.get("status") != "RESOLVED":
            continue
        device = db.devices.get(alert.get("device_id"))
        if device is None:
            continue
        if device["id"] not in reachable_set and device.get("status") != "DECOMMISSIONED":
            alert["status"] = "OPEN"
            touch(alert)
            touched.append(alert)
    for device in devices:
        device["battery_health_score"] = device_battery_health_score(
            device.get("battery_pct", 0),
            device.get("firmware_version"),
            _open_alert_count(device["id"]),
        )
    seen = {}
    for alert in touched:
        seen[alert["id"]] = alert
    return success(
        [serialize(row) for row in seen.values()], "array", 200
    )


API_ROUTES = [
    ("POST", "/devices", create_device),
    ("GET", "/devices", list_devices),
    ("POST", "/devices/<deviceId>/replace_battery", replace_battery),
    ("POST", "/devices/<deviceId>/lock-events", create_lock_event),
    ("POST", "/buildings/<buildingId>/device-scans", create_device_scan),
]