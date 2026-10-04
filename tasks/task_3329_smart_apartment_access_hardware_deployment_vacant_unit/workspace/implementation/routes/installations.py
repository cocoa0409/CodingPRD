"""Installation jobs: creation, start (schedule) and completion (PRD 3.8)."""

from flask import request

from calculations import (
    ESTIMATED_INSTALL_MINUTES,
    ESTIMATED_JOB_RESERVE_CENTS,
    INSTALL_BUFFER_MINUTES,
    installation_labor_hours,
    refresh_connectivity,
)
from db import add_minutes, clock, db, hours_between, iso, parse_instant, touch
from errors import (
    ERR_INSUFFICIENT_CONNECTIVITY,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NO_HUB_CONNECTIVITY,
    ERR_STALE_VERSION,
    ERR_UNIT_SCHEDULE_CONFLICT,
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
from svc_common import (
    get_building,
    get_installation_job,
    get_unit,
    has_install_conflict,
    new_record,
    recompute_budget,
)

DEVICE_TYPES = (
    "SMART_LOCK",
    "THERMOSTAT",
    "LEAK_SENSOR",
    "COMMUNITY_ACCESS",
    "HUB",
)


@require_roles("PropertyManager", "HardwareTechnician")
def create_installation_job(caller, buildingId):
    payload = body()
    validate_body(
        payload,
        required=(
            "device_type",
            "access_window_start",
            "access_window_end",
            "expected_building_version",
        ),
        optional=("unit_id", "requires_resident_coordination"),
    )
    building = get_building(buildingId)
    device_type = require_value(payload, "device_type")
    if device_type not in DEVICE_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "Unknown device_type: %s" % device_type)
    unit_id = payload.get("unit_id")
    unit = get_unit(unit_id) if unit_id is not None else None
    access_start = parse_instant(
        require_value(payload, "access_window_start"), "access_window_start"
    )
    access_end = parse_instant(
        require_value(payload, "access_window_end"), "access_window_end"
    )
    requires_coordination = optional_bool(
        payload, "requires_resident_coordination", False
    )

    refresh_connectivity(building)
    if device_type == "HUB" and not building.get("connectivity_ok"):
        raise ApiError(
            ERR_NO_HUB_CONNECTIVITY,
            "Installing a HUB requires the building to already pass connectivity",
        )

    expected = payload.get("expected_building_version")
    if expected is None:
        raise ApiError(
            ERR_INVALID_REQUEST, "Missing required field: expected_building_version"
        )

    property_id = building.get("property_id")
    committed_now = recompute_budget(property_id)
    _ensure_budget(property_id, committed_now + ESTIMATED_JOB_RESERVE_CENTS)

    if int(expected) != int(building.get("version", 1)):
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_building_version %s does not match the building's current version"
            % expected,
        )

    record = new_record(
        {
            "property_id": property_id,
            "building_id": building["id"],
            "unit_id": unit["id"] if unit is not None else None,
            "device_type": device_type,
            "requires_resident_coordination": requires_coordination,
            "access_window_start": iso(access_start),
            "access_window_end": iso(access_end),
            "scheduled_start_at": None,
            "status": "SCHEDULED",
            "labor_hours": 0,
            "_reserve_cents": ESTIMATED_JOB_RESERVE_CENTS,
            "_device_id": None,
            "_abort_reason": None,
        }
    )
    db.installation_jobs[record["id"]] = record
    building["version"] = building.get("version", 1) + 1
    building["updated_at"] = iso(clock.now)
    recompute_budget(property_id)
    return success(serialize(record), "object", 201)


def _ensure_budget(property_id, prospective_total):
    prop = db.properties.get(property_id)
    if prop is None:
        return
    if prospective_total > int(prop.get("temp_budget_cents_per_day") or 0):
        raise ApiError(
            "ERR_BUDGET_EXCEEDED",
            "Committing %d cents would exceed the property daily allowance"
            % prospective_total,
        )


@require_roles("HardwareTechnician")
def schedule_installation_job(caller, installationJobId):
    payload = body()
    validate_body(payload, optional=("scheduled_start_at",))
    job = get_installation_job(installationJobId)
    if job.get("status") != "SCHEDULED":
        raise ApiError(
            ERR_INVALID_STATE,
            "Installation job %s is not SCHEDULED" % installationJobId,
        )
    scheduled_start = payload.get("scheduled_start_at")
    if scheduled_start is None:
        scheduled_start = job.get("access_window_start")
    start = parse_instant(scheduled_start, "scheduled_start_at")
    job["scheduled_start_at"] = iso(start)
    job["_scheduled_at"] = iso(start)

    unit = db.units.get(job.get("unit_id")) if job.get("unit_id") else None
    if job.get("requires_resident_coordination"):
        if unit is None or unit.get("occupancy_status") != "OCCUPIED":
            raise ApiError(
                ERR_INVALID_STATE,
                "Resident coordination requires the target unit to be OCCUPIED",
            )
        if not _certified_visit_covers(unit["id"], start):
            raise ApiError(
                ERR_INVALID_STATE,
                "No NOTICE_CERTIFIED maintenance visit covers the scheduled start",
            )
    end = add_minutes(start, ESTIMATED_INSTALL_MINUTES)
    if unit is not None and has_install_conflict(
        unit["id"], start, end, INSTALL_BUFFER_MINUTES
    ):
        raise ApiError(
            ERR_UNIT_SCHEDULE_CONFLICT,
            "The install window collides with another occupation of the unit",
        )

    job["status"] = "IN_PROGRESS"
    device = new_record(
        {
            "unit_id": job.get("unit_id"),
            "building_id": job.get("building_id"),
            "device_type": job.get("device_type"),
            "firmware_version": "LATEST",
            "battery_pct": 100,
            "status": "PROVISIONED",
            "lock_state": "LOCKED",
            "battery_replacements": 0,
            "battery_health_score": None,
        }
    )
    db.devices[device["id"]] = device
    job["_device_id"] = device["id"]
    touch(job)
    recompute_budget(job.get("property_id"))
    return success(serialize(job), "object", 200)


def _certified_visit_covers(unit_id, moment):
    for visit in db.maintenance_visits.values():
        if visit.get("unit_id") != unit_id:
            continue
        if visit.get("status") != "NOTICE_CERTIFIED":
            continue
        visit_start = parse_instant(visit.get("start_at"), "start_at")
        visit_end = parse_instant(visit.get("end_at"), "end_at")
        if visit_start <= moment <= visit_end:
            return True
    return False


@require_roles("HardwareTechnician")
def complete_installation_job(caller, installationJobId):
    payload = body()
    validate_body(payload)
    job = get_installation_job(installationJobId)
    if job.get("status") != "IN_PROGRESS":
        raise ApiError(
            ERR_INVALID_STATE,
            "Installation job %s is not IN_PROGRESS" % installationJobId,
        )
    building = get_building(job["building_id"])
    connected = refresh_connectivity(building)
    device = db.devices.get(job.get("_device_id"))
    if connected:
        job["status"] = "COMPLETED"
        job["labor_hours"] = installation_labor_hours(job.get("device_type"))
        if device is not None:
            device["status"] = "ONLINE"
            touch(device)
        touch(job)
        recompute_budget(job.get("property_id"))
        return success(serialize(job), "object", 200)
    job["status"] = "ABORTED"
    job["_abort_reason"] = "CONNECTIVITY"
    if device is not None:
        device["status"] = "DECOMMISSIONED"
        touch(device)
    touch(job)
    recompute_budget(job.get("property_id"))
    return success(serialize(job), "object", 200)


@require_roles("PropertyManager", "HardwareTechnician")
def list_installation_jobs(caller):
    rows = list(db.installation_jobs.values())
    property_id = request.args.get("property_id")
    building_id = request.args.get("building_id")
    unit_id = request.args.get("unit_id")
    if property_id:
        rows = [row for row in rows if row.get("property_id") == property_id]
    if building_id:
        rows = [row for row in rows if row.get("building_id") == building_id]
    if unit_id:
        rows = [row for row in rows if row.get("unit_id") == unit_id]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


API_ROUTES = [
    ("POST", "/buildings/<buildingId>/installation-jobs", create_installation_job),
    (
        "POST",
        "/installation-jobs/<installationJobId>/schedule",
        schedule_installation_job,
    ),
    (
        "POST",
        "/installation-jobs/<installationJobId>/complete",
        complete_installation_job,
    ),
    ("GET", "/installation-jobs", list_installation_jobs),
]