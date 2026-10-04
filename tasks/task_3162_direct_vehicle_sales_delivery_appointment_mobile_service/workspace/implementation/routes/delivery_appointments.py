"""DeliveryAppointment routes."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB
from errors import fail
from repository import find, get, matches, serialize
from response import list_response, object_response
from routes.common import body, check_version, instant_field, counted, int_field, paged, require_owner, text_field
from services import calculation as calc
from services import delivery

bp = Blueprint("delivery_appointments", __name__)


@bp.post("/delivery-appointments")
def book_appointment():
    payload = body()
    order = get("order", text_field(payload, "order_id"))
    # PRD 3.12: the version comparison is entry 19, below the slot-conflict rule
    # of entry 11, so a request that would also collide with an occupied bay
    # surfaces the conflict rather than the staleness.
    center = get("center", text_field(payload, "delivery_center_id"))
    mode = text_field(payload, "delivery_mode")
    if mode not in ("CENTER", "HOME"):
        fail("ERR_INVALID_REQUEST", "delivery_mode must be CENTER or HOME.")
    appointment = delivery.book(
        order, center, mode,
        instant_field(payload, "scheduled_start"),
        instant_field(payload, "scheduled_end"),
        int_field(payload, "buyer_service_address_miles", None),
        expected_order_version=payload.get("expected_order_version"),
    )
    return object_response(serialize(appointment), 201)


@bp.get("/delivery-appointments")
def list_appointments():
    rows = [r for r in DB.appointments.values()
            if matches(request.args, "delivery_center_id", r["delivery_center_id"])
            and matches(request.args, "order_id", r["order_id"])
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/delivery-appointments/<appointment_id>")
def get_appointment(appointment_id):
    appointment = get("appointment", appointment_id)
    order = find("order", appointment["order_id"])
    if order is not None:
        require_owner(order)
    return object_response(serialize(appointment))


def appointment_and_order(appointment_id):
    appointment = get("appointment", appointment_id)
    order = get("order", appointment["order_id"])
    return appointment, order


@bp.post("/delivery-appointments/<appointment_id>/confirm")
def confirm_appointment(appointment_id):
    appointment, order = appointment_and_order(appointment_id)
    return object_response(serialize(delivery.confirm(appointment, order)))


@bp.post("/delivery-appointments/<appointment_id>/rebook")
def rebook_appointment(appointment_id):
    appointment, order = appointment_and_order(appointment_id)
    payload = body()
    check_version(payload, "expected_order_version", order)
    updated = delivery.rebook(
        appointment, order,
        instant_field(payload, "scheduled_start"),
        instant_field(payload, "scheduled_end"))
    return object_response(serialize(updated))


@bp.post("/delivery-appointments/<appointment_id>/cancel")
def cancel_appointment(appointment_id):
    appointment, order = appointment_and_order(appointment_id)
    return object_response(serialize(delivery.cancel(appointment, order)))


@bp.post("/delivery-appointments/<appointment_id>/complete")
def complete_appointment(appointment_id):
    appointment, order = appointment_and_order(appointment_id)
    payload = body()
    check_version(payload, "expected_order_version", order)
    result = text_field(payload, "acceptance_inspection_result")
    issues = payload.get("documented_issues")
    if issues is None:
        issues = []
    if not isinstance(issues, list):
        fail("ERR_INVALID_REQUEST", "documented_issues must be an array.")
    updated = delivery.complete(appointment, order, result, issues)
    return object_response(serialize(updated))