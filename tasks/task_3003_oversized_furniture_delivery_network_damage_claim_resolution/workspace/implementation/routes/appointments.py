"""Delivery appointments: OCC-guarded booking, complete, no-show, cancel."""
from datetime import timedelta

from flask import Blueprint, request

import clock
from db import db, new_id
from errors import (
    err_appointment_overlap,
    err_invalid_appointment_window,
    err_invalid_state,
    err_stale_version,
)
from middleware import require_roles
from response import success
from services import supplier_metrics
from services.common import get_or_404, list_response, stamp_new, touch
from validation import get_body, req_datetime, req_int, req_string

bp = Blueprint("appointments", __name__)


@bp.post("/appointments")
@require_roles("Customer", "HubOperator")
def book_appointment():
    body = get_body(request)
    # Existence: body fields in declared input order (shipment_id first).
    raw_shipment_id = body.get("shipment_id")
    shipment = get_or_404(db.shipments, raw_shipment_id if isinstance(raw_shipment_id, str) else None)
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    crew_id = req_string(body, "crew_id")
    expected_version = req_int(body, "expected_shipment_version")

    # State gate (priority 5) before endpoint-specific business rules.
    # OUT_FOR_DELIVERY is bookable only as a no-show rebooking (PRD §3.5: the
    # shipment stays OUT_FOR_DELIVERY on no-show "and a replacement
    # appointment may subsequently be booked") — i.e. when the shipment has
    # an appointment in NO_SHOW. Any other non-AT_HUB state is invalid.
    if shipment["current_state"] != "AT_HUB":
        rebooking = shipment["current_state"] == "OUT_FOR_DELIVERY" and any(
            a["shipment_id"] == shipment["id"] and a["status"] == "NO_SHOW"
            for a in db.appointments.values()
        )
        if not rebooking:
            raise err_invalid_state("Shipment must be AT_HUB to book an appointment")

    order = db.orders.get(shipment["order_id"])
    service_level = order["service_level"] if order is not None else None
    hub_id = shipment["hub_id"]

    # Window validation runs before the overlap check (PRD §3.5).
    if not window_start < window_end:
        raise err_invalid_appointment_window("window_start must be strictly before window_end")
    if window_end - window_start < timedelta(hours=2):
        raise err_invalid_appointment_window("window duration must be at least 2 hours")
    if window_start < clock.now():
        raise err_invalid_appointment_window("window_start must not be in the past")

    if service_level == "ROOM_OF_CHOICE":
        for appt in db.appointments.values():
            if (
                appt["status"] == "BOOKED"
                and appt["hub_id"] == hub_id
                and appt["crew_id"] == crew_id
            ):
                # Half-open intervals [start, end); back-to-back is allowed.
                if window_start < clock._parse_iso(appt["window_end"]) and clock._parse_iso(
                    appt["window_start"]
                ) < window_end:
                    raise err_appointment_overlap()

    # OCC check (scaffold priority 17): last business rule before committing.
    if expected_version != shipment["version"]:
        raise err_stale_version()

    appointment = stamp_new(
        {
            "id": new_id(),
            "shipment_id": shipment["id"],
            "service_level": service_level,
            "window_start": clock.format_dt(window_start),
            "window_end": clock.format_dt(window_end),
            "hub_id": hub_id,
            "crew_id": crew_id,
            "status": "BOOKED",
        }
    )
    db.appointments[appointment["id"]] = appointment

    shipment["current_state"] = "OUT_FOR_DELIVERY"
    touch(shipment)  # increments Shipment.version by 1
    if order is not None:
        order["order_state"] = "OUT_FOR_DELIVERY"
        order["fulfillment_state"] = "SCHEDULED"
        touch(order)
    return success(appointment, status=201)


_APPT_STATES = {"BOOKED", "COMPLETED", "NO_SHOW", "CANCELLED"}


@bp.get("/appointments")
@require_roles("NetworkAdmin", "HubOperator", "Customer")
def list_appointments():
    return list_response(
        db.appointments,
        [
            ("shipment_id", "shipment_id", None),
            ("hub_id", "hub_id", None),
            ("status", "status", _APPT_STATES),
        ],
    )


@bp.get("/appointments/<appointmentId>")
@require_roles("NetworkAdmin", "HubOperator", "Customer")
def get_appointment(appointmentId):
    return success(get_or_404(db.appointments, appointmentId))


@bp.post("/appointments/<appointmentId>/complete")
@require_roles("HubOperator")
def complete_appointment(appointmentId):
    appointment = get_or_404(db.appointments, appointmentId)
    if appointment["status"] != "BOOKED":
        raise err_invalid_state("Appointment must be BOOKED to complete")
    appointment["status"] = "COMPLETED"
    touch(appointment)
    shipment = db.shipments.get(appointment["shipment_id"])
    if shipment is not None:
        shipment["current_state"] = "DELIVERED"
        shipment["delivered_at"] = clock.now_str()
        touch(shipment)
        order = db.orders.get(shipment["order_id"])
        if order is not None:
            order["order_state"] = "DELIVERED"
            order["fulfillment_state"] = "FULFILLED"
            touch(order)
        supplier_metrics.recompute_supplier(shipment["supplier_id"])
    return success(appointment)


@bp.post("/appointments/<appointmentId>/mark-no-show")
@require_roles("HubOperator")
def mark_no_show_appointment(appointmentId):
    appointment = get_or_404(db.appointments, appointmentId)
    if appointment["status"] != "BOOKED":
        raise err_invalid_state("Appointment must be BOOKED to mark no-show")
    appointment["status"] = "NO_SHOW"
    touch(appointment)
    return success(appointment)


@bp.post("/appointments/<appointmentId>/cancel")
@require_roles("Customer", "HubOperator")
def cancel_appointment(appointmentId):
    appointment = get_or_404(db.appointments, appointmentId)
    if appointment["status"] != "BOOKED":
        raise err_invalid_state("Appointment must be BOOKED to cancel")
    appointment["status"] = "CANCELLED"
    touch(appointment)
    shipment = db.shipments.get(appointment["shipment_id"])
    if shipment is not None and shipment["current_state"] == "OUT_FOR_DELIVERY":
        shipment["current_state"] = "AT_HUB"
        touch(shipment)
    return success(appointment)
