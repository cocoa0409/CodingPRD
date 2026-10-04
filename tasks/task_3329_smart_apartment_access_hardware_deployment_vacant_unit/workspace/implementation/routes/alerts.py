"""Device alerts, work orders and the repair loop (PRD 3.9)."""

from flask import request

from db import clock, db, iso, touch
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ApiError,
)
from middleware import require_roles
from records import (
    body,
    optional_bool,
    require_value,
    serialize,
    validate_body,
)
from response import paged, success
from svc_common import get_device, get_device_alert, get_work_order, new_record


@require_roles("PlatformAdmin", "PropertyManager", "HardwareTechnician")
def list_device_alerts(caller):
    rows = list(db.device_alerts.values())
    building_id = request.args.get("building_id")
    device_id = request.args.get("device_id")
    if building_id:
        rows = [row for row in rows if row.get("building_id") == building_id]
    if device_id:
        rows = [row for row in rows if row.get("device_id") == device_id]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


@require_roles("PropertyManager", "HardwareTechnician")
def create_work_order(caller, deviceAlertId):
    payload = body()
    validate_body(
        payload,
        required=("expected_device_alert_version",),
        optional=("assigned_technician_id",),
    )
    alert = get_device_alert(deviceAlertId)
    expected = payload.get("expected_device_alert_version")
    if expected is None:
        raise ApiError(
            ERR_INVALID_REQUEST, "Missing required field: expected_device_alert_version"
        )
    try:
        expected_int = int(expected)
    except (TypeError, ValueError):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "expected_device_alert_version must be an integer",
        )
    if expected_int != int(alert.get("version", 1)):
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_device_alert_version %s does not match the alert's current version"
            % expected,
        )
    record = new_record(
        {
            "device_id": alert.get("device_id"),
            "alert_id": alert["id"],
            "assigned_technician_id": payload.get("assigned_technician_id"),
            "status": "OPEN",
            "battery_replaced": False,
        }
    )
    db.work_orders[record["id"]] = record
    touch(alert)
    return success(serialize(record), "object", 201)


@require_roles("HardwareTechnician")
def assign_work_order(caller, workOrderId):
    payload = body()
    validate_body(
        payload,
        required=("technician_id",),
        optional=("replaced_battery", "confirm_repair"),
    )
    work_order = get_work_order(workOrderId)
    technician_id = require_value(payload, "technician_id")
    replaced_battery = optional_bool(payload, "replaced_battery", False)
    confirm_repair = optional_bool(payload, "confirm_repair", False)

    status = work_order.get("status")
    if status == "CLOSED":
        raise ApiError(
            ERR_ALREADY_TERMINAL, "Work order %s is CLOSED" % workOrderId
        )
    if status not in ("OPEN", "ASSIGNED"):
        raise ApiError(
            ERR_INVALID_STATE, "Work order %s is not assignable" % workOrderId
        )

    work_order["assigned_technician_id"] = technician_id
    if replaced_battery:
        work_order["battery_replaced"] = True

    alert = db.device_alerts.get(work_order.get("alert_id"))
    device = db.devices.get(work_order.get("device_id"))

    if status == "OPEN":
        work_order["status"] = "ASSIGNED"
        touch(work_order)
        if alert is not None and alert.get("status") == "OPEN":
            alert["status"] = "ACKNOWLEDGED"
            touch(alert)
        return success(serialize(work_order), "object", 200)

    # status == ASSIGNED -> CLOSED
    if not confirm_repair:
        touch(work_order)
        return success(serialize(work_order), "object", 200)
    device_online = device is not None and device.get("status") == "ONLINE"
    if not device_online and not work_order.get("battery_replaced"):
        raise ApiError(
            ERR_INVALID_STATE,
            "The device must be ONLINE or the battery must have been replaced",
        )
    work_order["status"] = "CLOSED"
    touch(work_order)
    if alert is not None and alert.get("status") != "RESOLVED":
        alert["status"] = "RESOLVED"
        touch(alert)
    if work_order.get("battery_replaced") and device is not None:
        device["battery_replacements"] = device.get("battery_replacements", 0) + 1
        touch(device)
    return success(serialize(work_order), "object", 200)


@require_roles("PropertyManager", "HardwareTechnician")
def list_work_orders(caller):
    rows = list(db.work_orders.values())
    device_id = request.args.get("device_id")
    alert_id = request.args.get("alert_id")
    if device_id:
        rows = [row for row in rows if row.get("device_id") == device_id]
    if alert_id:
        rows = [row for row in rows if row.get("alert_id") == alert_id]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


API_ROUTES = [
    ("GET", "/device-alerts", list_device_alerts),
    ("POST", "/device-alerts/<deviceAlertId>/work-orders", create_work_order),
    ("POST", "/work-orders/<workOrderId>/assign", assign_work_order),
    ("GET", "/work-orders", list_work_orders),
]