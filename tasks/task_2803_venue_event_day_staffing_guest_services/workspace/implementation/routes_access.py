"""Accessibility service pools and the guest bookings held against them."""

from flask import Blueprint

import calc
import services as svc
from core import (
    all_rows,
    auth,
    bad_window,
    body_dict,
    conflict,
    db,
    invalid,
    lookup,
    new_record,
    now,
    pagination,
    q_enum,
    q_str,
    req_dt,
    req_enum,
    req_int,
    req_str,
    respond,
    respond_list,
    touch,
    update,
    v_enum,
    v_int,
    MISSING,
)
from serialize import accessibility_request_json, accessibility_resource_json

bp = Blueprint("access", __name__)

RESOURCE_TYPES = (
    "WHEELCHAIR_ESCORT",
    "ASSISTIVE_LISTENING_UNIT",
    "COMPANION_SEAT_BLOCK",
)
RESOURCE_STATUSES = ("AVAILABLE", "MAINTENANCE", "WITHDRAWN")
REQUEST_STATUSES = (
    "REQUESTED",
    "CONFIRMED",
    "IN_SERVICE",
    "COMPLETED",
    "DENIED",
    "CANCELLED",
)
TARGET_STATUSES = ("CONFIRMED", "IN_SERVICE", "COMPLETED", "DENIED", "CANCELLED")

# The six declared movements of §3.9 and no others.
DECLARED_MOVES = (
    ("REQUESTED", "CONFIRMED"),
    ("CONFIRMED", "IN_SERVICE"),
    ("IN_SERVICE", "COMPLETED"),
    ("REQUESTED", "DENIED"),
    ("REQUESTED", "CANCELLED"),
    ("CONFIRMED", "CANCELLED"),
)

READ_ROLES = (
    "GuestExperienceDirector",
    "StaffingCoordinator",
    "GuestServicesSupervisor",
)


# ---------------------------------------------------------------------------
# accessibility pools
# ---------------------------------------------------------------------------

@bp.post("/accessibility-resources")
def create_accessibility_resource():
    auth("GuestServicesSupervisor")
    body = body_dict()
    event_id = req_str(body, "event_id")
    resource_type = req_enum(body, "resource_type", RESOURCE_TYPES)
    zone_code = req_str(body, "zone_code")
    unit_count = req_int(body, "unit_count", minimum=1)
    lookup("events", event_id)
    row = new_record(
        "accessibility_resources",
        {
            "event_id": event_id,
            "resource_type": resource_type,
            "zone_code": zone_code,
            "unit_count": unit_count,
            "peak_committed_units": 0,
            "status": "AVAILABLE",
        },
    )
    return respond(accessibility_resource_json(row), 201)


@bp.get("/accessibility-resources/<resource_id>")
def read_accessibility_resource(resource_id):
    auth(*READ_ROLES)
    return respond(
        accessibility_resource_json(lookup("accessibility_resources", resource_id))
    )


@bp.get("/accessibility-resources")
def list_accessibility_resources():
    auth(*READ_ROLES)
    event_id = q_str("event_id")
    resource_type = q_enum("resource_type", RESOURCE_TYPES)
    status = q_enum("status", RESOURCE_STATUSES)
    zone_code = q_str("zone_code")
    limit, offset = pagination()
    rows = all_rows("accessibility_resources")
    if event_id is not None:
        rows = [r for r in rows if r["event_id"] == event_id]
    if resource_type is not None:
        rows = [r for r in rows if r["resource_type"] == resource_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if zone_code is not None:
        rows = [r for r in rows if r["zone_code"] == zone_code]
    window = rows[offset:offset + limit]
    return respond_list(
        [accessibility_resource_json(r) for r in window], limit, offset, len(rows)
    )


@bp.patch("/accessibility-resources/<resource_id>")
def update_accessibility_resource(resource_id):
    auth("GuestServicesSupervisor")
    body = body_dict()
    changes = {}
    if "unit_count" in body:
        changes["unit_count"] = v_int(body["unit_count"], "unit_count", minimum=1)
    if "status" in body:
        changes["status"] = v_enum(body["status"], "status", RESOURCE_STATUSES)
    row = lookup("accessibility_resources", resource_id)
    # the committed peak is re-derived first, so the refusal is judged against
    # the pool's live commitment rather than a stale stored figure
    peak = calc.peak_occupancy(svc.committed_bookings(row))
    if "unit_count" in changes and changes["unit_count"] < peak:
        raise conflict(
            "ERR_ACCESSIBILITY_CAPACITY_EXCEEDED",
            "unit_count %d would fall below the committed peak of %d."
            % (changes["unit_count"], peak),
        )
    # taking a pool out of service never cancels a confirmed booking
    changes["peak_committed_units"] = peak
    if not update(row, **changes):
        touch(row)
    return respond(accessibility_resource_json(row))


# ---------------------------------------------------------------------------
# guest bookings
# ---------------------------------------------------------------------------

@bp.post("/accessibility-requests")
def create_accessibility_request():
    auth("GuestServicesSupervisor")
    body = body_dict()
    resource_id = req_str(body, "resource_id")
    guest_reference = req_str(body, "guest_reference")
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    units = req_int(body, "units_requested", minimum=1)
    companions = body.get("companion_seats_requested", MISSING)
    companions = (
        0
        if companions is MISSING
        else v_int(companions, "companion_seats_requested", minimum=0)
    )
    # rung 4 outranks the pool's existence check
    if window_end <= window_start:
        raise bad_window("window_end must be strictly after window_start.")
    lookup("accessibility_resources", resource_id)
    row = new_record(
        "accessibility_requests",
        {
            "resource_id": resource_id,
            "guest_reference": guest_reference,
            "window_start": window_start,
            "window_end": window_end,
            "units_requested": units,
            "companion_seats_requested": companions,
            "confirmed_at": None,
            "service_started_at": None,
            "completed_at": None,
            "denial_reason": None,
            "status": "REQUESTED",
        },
    )
    return respond(accessibility_request_json(row), 201)


@bp.get("/accessibility-requests/<request_id>")
def read_accessibility_request(request_id):
    auth(*READ_ROLES)
    return respond(
        accessibility_request_json(lookup("accessibility_requests", request_id))
    )


@bp.get("/accessibility-requests")
def list_accessibility_requests():
    auth(*READ_ROLES)
    resource_id = q_str("resource_id")
    status = q_enum("status", REQUEST_STATUSES)
    limit, offset = pagination()
    rows = all_rows("accessibility_requests")
    if resource_id is not None:
        rows = [r for r in rows if r["resource_id"] == resource_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window = rows[offset:offset + limit]
    return respond_list(
        [accessibility_request_json(r) for r in window], limit, offset, len(rows)
    )


@bp.post("/accessibility-requests/<request_id>/transition")
def transition_accessibility_request(request_id):
    auth("GuestServicesSupervisor")
    body = body_dict()
    target = req_enum(body, "target_status", TARGET_STATUSES)
    reason = body.get("denial_reason", MISSING)
    if reason is MISSING or reason is None:
        reason = None
    else:
        reason = req_str(body, "denial_reason")
    if target == "DENIED" and reason is None:
        raise invalid("denial_reason is required for a DENIED booking.")

    row = lookup("accessibility_requests", request_id)
    current = row["status"]
    if (current, target) not in DECLARED_MOVES:
        raise conflict(
            "ERR_ACCESS_REQUEST_STATE_INVALID",
            "%s -> %s is not a declared booking movement." % (current, target),
        )
    resource = db.accessibility_resources[row["resource_id"]]
    event = db.events[resource["event_id"]]

    if target == "CONFIRMED":
        if event["status"] not in ("PLANNED", "IN_PROGRESS"):
            raise conflict(
                "ERR_EVENT_STATE_INVALID",
                "Confirming a booking requires the event in PLANNED or IN_PROGRESS.",
            )
        if resource["status"] != "AVAILABLE":
            raise conflict(
                "ERR_RESOURCE_NOT_AVAILABLE",
                "The pool stands in %s, not AVAILABLE." % resource["status"],
            )
        candidate = dict(row)
        candidate["status"] = "CONFIRMED"
        if svc.peak_with_candidate(resource, candidate) > resource["unit_count"]:
            raise conflict(
                "ERR_ACCESSIBILITY_CAPACITY_EXCEEDED",
                "The pool has no room across the whole requested window.",
            )
        update(row, status="CONFIRMED", confirmed_at=now())
        svc.recompute_peak(resource)
    elif target == "IN_SERVICE":
        if event["status"] != "IN_PROGRESS":
            raise conflict(
                "ERR_EVENT_STATE_INVALID",
                "Beginning service requires the event exactly in IN_PROGRESS.",
            )
        if resource["status"] != "AVAILABLE":
            raise conflict(
                "ERR_RESOURCE_NOT_AVAILABLE",
                "The pool stands in %s, not AVAILABLE." % resource["status"],
            )
        # the units stay occupied across this move, so the pool is untouched
        update(row, status="IN_SERVICE", service_started_at=now())
    elif target == "COMPLETED":
        update(row, status="COMPLETED", completed_at=now())
        svc.recompute_peak(resource)
    elif target == "DENIED":
        # a merely requested booking never held units, so nothing is released
        update(row, status="DENIED", denial_reason=reason)
    else:
        released = current == "CONFIRMED"
        update(row, status="CANCELLED")
        if released:
            svc.recompute_peak(resource)
    return respond(accessibility_request_json(row))
