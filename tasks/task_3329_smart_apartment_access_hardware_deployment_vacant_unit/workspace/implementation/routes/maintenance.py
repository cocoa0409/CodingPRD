"""Maintenance visits: request, notice certification, completion (PRD 3.7)."""

from flask import request

from calculations import (
    NOTICE_WINDOW_CLOSE_HOUR,
    NOTICE_WINDOW_OPEN_HOUR,
    REQUIRED_NOTICE_HOURS_EMERGENCY,
    REQUIRED_NOTICE_HOURS_STANDARD,
    maintenance_accrual_cents,
)
from db import add_hours, clock, db, hours_between, iso, parse_instant, touch
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOTICE_REQUIREMENT_UNMET,
    ERR_OUTSIDE_NOTICE_WINDOW,
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
    ensure_budget,
    get_maintenance_visit,
    get_unit,
    has_schedule_conflict,
    new_record,
    recompute_budget,
)


@require_roles("PropertyManager", "MaintenanceTechnician")
def create_maintenance_visit(caller, unitId):
    payload = body()
    validate_body(
        payload,
        required=("technician_id", "start_at", "end_at"),
        optional=("is_emergency",),
    )
    unit = get_unit(unitId)
    start = parse_instant(require_value(payload, "start_at"), "start_at")
    end = parse_instant(require_value(payload, "end_at"), "end_at")
    is_emergency = optional_bool(payload, "is_emergency", False)
    if has_schedule_conflict(unit["id"], start, end):
        raise ApiError(
            ERR_UNIT_SCHEDULE_CONFLICT,
            "The requested window overlaps an existing occupation of the unit",
        )
    record = new_record(
        {
            "unit_id": unit["id"],
            "technician_id": require_value(payload, "technician_id"),
            "start_at": iso(start),
            "end_at": iso(end),
            "planned_hours": round(hours_between(start, end), 4),
            "actual_hours": None,
            "is_emergency": is_emergency,
            "notice_mailed_at": None,
            "status": "REQUESTED",
            "accrued_cost_cents": 0,
            "_property_id": unit.get("property_id"),
        }
    )
    db.maintenance_visits[record["id"]] = record
    return success(serialize(record), "object", 201)


@require_roles("PropertyManager")
def certify_notice(caller, maintenanceVisitId):
    payload = body()
    validate_body(payload, required=("notice_mailed_at",))
    visit = get_maintenance_visit(maintenanceVisitId)
    if visit.get("status") != "REQUESTED":
        raise ApiError(
            ERR_INVALID_STATE,
            "Maintenance visit %s is not REQUESTED" % maintenanceVisitId,
        )
    notice_at = parse_instant(
        require_value(payload, "notice_mailed_at"), "notice_mailed_at"
    )
    start = parse_instant(visit.get("start_at"), "start_at")
    required = (
        REQUIRED_NOTICE_HOURS_EMERGENCY
        if visit.get("is_emergency")
        else REQUIRED_NOTICE_HOURS_STANDARD
    )
    required_at = add_hours(start, -required)
    if notice_at > required_at:
        raise ApiError(
            ERR_NOTICE_REQUIREMENT_UNMET,
            "Notice was served less than %d hours before the visit start" % required,
        )
    local_hour = _local_hour(start)
    if not (NOTICE_WINDOW_OPEN_HOUR <= local_hour < NOTICE_WINDOW_CLOSE_HOUR):
        raise ApiError(
            ERR_OUTSIDE_NOTICE_WINDOW,
            "The visit start hour %d falls outside the legal notice window"
            % local_hour,
        )
    visit["notice_mailed_at"] = iso(notice_at)
    visit["status"] = "NOTICE_CERTIFIED"
    visit["accrued_cost_cents"] = maintenance_accrual_cents(
        visit.get("is_emergency"), visit.get("planned_hours"), final=False
    )
    touch(visit)
    property_id = visit.get("_property_id")
    prospective = recompute_budget(property_id)
    prop = db.properties.get(property_id)
    if prop is not None and prospective > int(prop.get("temp_budget_cents_per_day") or 0):
        # roll back the certification atomically (priority 20 beats nothing later)
        visit["status"] = "REQUESTED"
        visit["accrued_cost_cents"] = 0
        visit["notice_mailed_at"] = None
        touch(visit)
        recompute_budget(property_id)
        raise ApiError(
            "ERR_BUDGET_EXCEEDED",
            "Certifying this visit would exceed the property daily allowance",
        )
    return success(serialize(visit), "object", 200)


def _local_hour(moment):
    """§2.6 pins the window to [08:00, 20:00); the pinned clock is UTC."""
    return moment.hour


@require_roles("PropertyManager", "MaintenanceTechnician")
def complete_maintenance_visit(caller, maintenanceVisitId):
    payload = body()
    validate_body(payload, optional=("actual_hours", "cancelled"))
    visit = get_maintenance_visit(maintenanceVisitId)
    # PRD 2.12 priority 6: a resource already in a terminal state is refused with
    # ERR_ALREADY_TERMINAL before the state-gate of priority 5 is consulted.
    # COMPLETED and CANCELLED are the visit's two terminal states.
    if visit.get("status") in ("CANCELLED", "COMPLETED"):
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "Maintenance visit %s is already terminal" % maintenanceVisitId,
        )
    if visit.get("status") != "NOTICE_CERTIFIED":
        raise ApiError(
            ERR_INVALID_STATE,
            "Maintenance visit %s is not NOTICE_CERTIFIED" % maintenanceVisitId,
        )
    property_id = visit.get("_property_id")
    cancelled = optional_bool(payload, "cancelled", False)
    if cancelled:
        if caller.role != "PropertyManager":
            raise ApiError(
                "ERR_FORBIDDEN", "Only a PropertyManager may cancel a visit"
            )
        visit["status"] = "CANCELLED"
        visit["accrued_cost_cents"] = 0
        touch(visit)
        recompute_budget(property_id)
        return success(serialize(visit), "object", 200)
    actual_hours = payload.get("actual_hours")
    if actual_hours is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: actual_hours")
    if not isinstance(actual_hours, (int, float)) or actual_hours <= 0:
        raise ApiError(
            ERR_INVALID_REQUEST, "actual_hours must be greater than zero"
        )
    visit["actual_hours"] = actual_hours
    visit["status"] = "COMPLETED"
    visit["accrued_cost_cents"] = maintenance_accrual_cents(
        visit.get("is_emergency"), actual_hours, final=True
    )
    touch(visit)
    prospective = recompute_budget(property_id)
    prop = db.properties.get(property_id)
    if prop is not None and prospective > int(prop.get("temp_budget_cents_per_day") or 0):
        raise ApiError(
            "ERR_BUDGET_EXCEEDED",
            "Completing this visit would exceed the property daily allowance",
        )
    return success(serialize(visit), "object", 200)


@require_roles("PropertyManager", "MaintenanceTechnician")
def list_maintenance_visits(caller):
    rows = list(db.maintenance_visits.values())
    unit_id = request.args.get("unit_id")
    technician_id = request.args.get("technician_id")
    if unit_id:
        rows = [row for row in rows if row.get("unit_id") == unit_id]
    if technician_id:
        rows = [row for row in rows if row.get("technician_id") == technician_id]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


API_ROUTES = [
    ("POST", "/units/<unitId>/maintenance-visits", create_maintenance_visit),
    (
        "POST",
        "/maintenance-visits/<maintenanceVisitId>/certify_notice",
        certify_notice,
    ),
    (
        "POST",
        "/maintenance-visits/<maintenanceVisitId>/complete",
        complete_maintenance_visit,
    ),
    ("GET", "/maintenance-visits", list_maintenance_visits),
]