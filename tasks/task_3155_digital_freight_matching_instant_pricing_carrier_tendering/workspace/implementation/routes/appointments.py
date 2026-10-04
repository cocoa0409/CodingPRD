"""Appointment endpoints."""

from flask import request

from db import db, serialize
from middleware import roles_required
from response import array_response, object_response, paginate
from routers import body
from services import scheduling
from services.common import get_appointment


def register(app):
    @app.route("/v1/appointments", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin")
    def list_appointments():
        rows = scheduling.appointment_list(list(db.appointments.values()), request.args)
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("AppointmentSlot", row) for row in window], pagination)

    @app.route("/v1/appointments/<appointment_id>", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin")
    def get_appointment_route(appointment_id):
        return object_response(serialize("AppointmentSlot", get_appointment(appointment_id)))

    @app.route("/v1/appointments/<appointment_id>/reschedule", methods=["POST"])
    @roles_required("Carrier", "PlatformAdmin")
    def reschedule(appointment_id):
        slot = scheduling.reschedule(appointment_id, body())
        return object_response(serialize("AppointmentSlot", slot))

    @app.route("/v1/appointments/<appointment_id>/complete", methods=["POST"])
    @roles_required("Carrier", "PlatformAdmin")
    def complete(appointment_id):
        slot = scheduling.complete(appointment_id)
        return object_response(serialize("AppointmentSlot", slot))

    @app.route("/v1/appointments/<appointment_id>/cancel", methods=["POST"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin")
    def cancel(appointment_id):
        slot = scheduling.cancel(appointment_id)
        return object_response(serialize("AppointmentSlot", slot))

    @app.route("/v1/appointments/<appointment_id>/restore", methods=["POST"])
    @roles_required("Carrier", "PlatformAdmin")
    def restore(appointment_id):
        slot = scheduling.restore(appointment_id)
        return object_response(serialize("AppointmentSlot", slot))