"""Install appointment windows and visit outcomes (PRD 3.8)."""

from flask import Blueprint

import auth
import calc
import envelope
import listing
import serialize
import shape
from errors import ApiError
from store import add_days, add_minutes, bump, db, insert, must_find, new_row, now, ordered, rows

bp = Blueprint("appointments", __name__)

READ_ROLES = (
    "ProgramManager",
    "InstallCoordinator",
    "ClaimsAssessor",
    "ClaimsApprover",
    "Subscriber",
)
REQUIRED_CREW_TYPE = {
    "DROP_BURY": "BURY",
    "AERIAL_DROP": "AERIAL",
    "RESTORATION_FOLLOWUP": "RESTORATION",
}
MIN_WINDOW_MINUTES = 30
MAX_WINDOW_MINUTES = 480


def _zone_of(preorder):
    return db.build_zones.get(preorder["build_zone_id"])


def _campaign_of(preorder):
    zone = _zone_of(preorder)
    return db.campaigns.get(zone["campaign_id"]) if zone else None


@bp.post("/install-appointments")
def create_appointment():
    auth.gate(("InstallCoordinator",))
    data = shape.body()
    preorder = listing.resolve(data, "preorder_id", "preorders")
    crew = listing.resolve(data, "crew_id", "install_crews")
    parent = listing.resolve(data, "parent_appointment_id", "install_appointments")
    shape.req_id(data, "preorder_id")
    shape.req_id(data, "crew_id")
    appointment_type = shape.req_enum(data, "appointment_type", calc.APPOINTMENT_TYPES)
    start = shape.req_dt(data, "window_start_at")
    end = shape.req_dt(data, "window_end_at")
    expected_crew_version = shape.req_int(data, "expected_crew_version")
    if appointment_type == "RESTORATION_FOLLOWUP":
        if parent is None:
            shape.bad("parent_appointment_id", "is required for a restoration follow-up")
    elif parent is not None:
        shape.bad("parent_appointment_id", "is only permitted on a restoration follow-up")

    if parent is not None and parent["preorder_id"] != preorder["id"]:
        raise ApiError(
            "ERR_ADDRESS_LINKAGE_MISMATCH",
            "the parent appointment serves a different preorder",
        )
    if crew["crew_type"] != REQUIRED_CREW_TYPE[appointment_type]:
        raise ApiError("ERR_CREW_TYPE_MISMATCH", "this crew is not certified for that work")
    if parent is not None and parent["status"] != "COMPLETED":
        raise ApiError(
            "ERR_INSTALL_APPOINTMENT_STATE_INVALID",
            "the parent appointment is not completed",
        )
    if expected_crew_version != crew["version"]:
        raise ApiError("ERR_STALE_CREW_VERSION", "the crew has moved on since it was read")
    zone = _zone_of(preorder)
    if zone is None or zone["construction_status"] not in ("IN_CONSTRUCTION", "SERVICE_READY"):
        raise ApiError(
            "ERR_ZONE_CONSTRUCTION_NOT_ACTIVE", "the zone is not actively under construction"
        )
    _check_window(start, end)
    duration = int((end - start).total_seconds() // 60)
    occupied = duration + crew["travel_buffer_minutes"]
    if parent is not None:
        if not parent["restoration_required"] or parent["restoration_satisfied_at"] is not None:
            raise ApiError(
                "ERR_RESTORATION_WINDOW_MISSED",
                "the parent appointment owes no restoration",
            )
        if parent["restoration_due_by"] is None or start > parent["restoration_due_by"]:
            raise ApiError(
                "ERR_RESTORATION_WINDOW_MISSED",
                "the follow-up window starts after the restoration deadline",
            )
    _check_conflict(crew, start, end)
    if appointment_type == "DROP_BURY":
        _check_bury_cap(zone, start, end)
    _check_daily_capacity(crew, start, occupied)
    address = db.service_addresses.get(preorder["service_address_id"])
    if address is not None and address["serviceability"] == "NOT_SERVICEABLE":
        raise ApiError("ERR_ADDRESS_NOT_SERVICEABLE", "this address cannot be served")
    row = new_row(
        {
            "preorder_id": preorder["id"],
            "crew_id": crew["id"],
            "parent_appointment_id": parent["id"] if parent else None,
            "appointment_type": appointment_type,
            "window_start_at": start,
            "window_end_at": end,
            "status": "SCHEDULED",
            "occupied_minutes": occupied,
            "restoration_required": False,
            "restoration_due_by": None,
            "restoration_satisfied_at": None,
            "completed_at": None,
            "cancellation_reason": None,
        }
    )
    insert("install_appointments", row)
    bump(crew)
    return envelope.created(serialize.install_appointment(row))


def _check_window(start, end):
    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW", "window_end_at must be after window_start_at")
    for instant in (start, end):
        if instant.second != 0 or instant.microsecond != 0:
            raise ApiError("ERR_INVALID_WINDOW", "windows must land on exact minutes")
    duration = int((end - start).total_seconds() // 60)
    if duration < MIN_WINDOW_MINUTES or duration > MAX_WINDOW_MINUTES:
        raise ApiError("ERR_INVALID_WINDOW", "the window duration is out of range")
    if start < now():
        raise ApiError("ERR_INVALID_WINDOW", "the window may not start in the past")


def _check_conflict(crew, start, end):
    buffer_minutes = crew["travel_buffer_minutes"]
    for existing in calc.crew_appointments(crew["id"]):
        if existing["status"] != "SCHEDULED":
            continue
        existing_end = add_minutes(existing["window_end_at"], buffer_minutes)
        new_end = add_minutes(end, buffer_minutes)
        if start < existing_end and existing["window_start_at"] < new_end:
            raise ApiError("ERR_CREW_WINDOW_CONFLICT", "this crew already holds that interval")


def _check_bury_cap(zone, start, end):
    overlaps = 0
    for existing in calc.zone_appointments(zone["id"]):
        if existing["status"] != "SCHEDULED":
            continue
        if existing["appointment_type"] != "DROP_BURY":
            continue
        if existing["window_start_at"] < end and start < existing["window_end_at"]:
            overlaps += 1
    if overlaps >= zone["max_concurrent_bury_ops"]:
        raise ApiError(
            "ERR_ZONE_BURY_CONCURRENCY_EXCEEDED",
            "too many simultaneous drop-bury windows in this zone",
        )


def _check_daily_capacity(crew, start, occupied):
    booked = 0
    for existing in calc.crew_appointments(crew["id"]):
        if existing["status"] != "SCHEDULED":
            continue
        if existing["window_start_at"].date() == start.date():
            booked += existing["occupied_minutes"]
    if booked + occupied > crew["daily_capacity_minutes"]:
        raise ApiError(
            "ERR_CREW_DAILY_CAPACITY_EXCEEDED", "the crew's daily capacity is exhausted"
        )


@bp.get("/install-appointments/<appointment_id>")
def read_appointment(appointment_id):
    auth.gate(READ_ROLES)
    row = must_find("install_appointments", appointment_id)
    return envelope.ok(serialize.install_appointment(row))


@bp.get("/install-appointments")
def list_appointments():
    auth.gate(READ_ROLES)
    items = listing.apply_filters(
        ordered(rows("install_appointments")),
        (
            listing.fk("preorder_id", "preorder_id", "preorders"),
            listing.fk("crew_id", "crew_id", "install_crews"),
            listing.fk("parent_appointment_id", "parent_appointment_id", "install_appointments"),
            listing.enum("status", "status", calc.APPOINTMENT_STATUSES),
            listing.enum("appointment_type", "appointment_type", calc.APPOINTMENT_TYPES),
        ),
    )
    return envelope.list_response(items, serialize.install_appointment)


@bp.post("/install-appointments/<appointment_id>/outcome")
def record_outcome(appointment_id):
    auth.gate(("InstallCoordinator",))
    appointment = must_find("install_appointments", appointment_id)
    data = shape.body()
    outcome = shape.req_enum(data, "outcome", calc.OUTCOMES)
    restoration_required = shape.opt_bool(data, "restoration_required", False)
    cancellation_reason = shape.opt_enum(
        data, "cancellation_reason", calc.CANCELLATION_REASONS
    )
    if appointment["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INSTALL_APPOINTMENT_STATE_INVALID",
            "this appointment already has an outcome",
        )
    preorder = db.preorders.get(appointment["preorder_id"])
    appointment["status"] = outcome
    if outcome == "COMPLETED":
        appointment["completed_at"] = now()
        appointment["restoration_required"] = restoration_required
        if restoration_required:
            campaign = _campaign_of(preorder) if preorder else None
            days = campaign["restoration_sla_days"] if campaign else 0
            appointment["restoration_due_by"] = add_days(appointment["completed_at"], days)
    elif outcome == "CANCELLED":
        appointment["cancellation_reason"] = cancellation_reason
    bump(appointment)
    if outcome == "COMPLETED" and appointment["appointment_type"] == "RESTORATION_FOLLOWUP":
        parent = db.install_appointments.get(appointment["parent_appointment_id"])
        if parent is not None and parent["restoration_satisfied_at"] is None:
            parent["restoration_satisfied_at"] = now()
            bump(parent)
    crew = db.install_crews.get(appointment["crew_id"])
    if crew is not None:
        bump(crew)
    return envelope.ok(serialize.install_appointment(appointment))
