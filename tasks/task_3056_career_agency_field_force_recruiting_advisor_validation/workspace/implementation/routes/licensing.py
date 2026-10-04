"""ProductLicense, SecuritiesRegistration and CarrierAppointment endpoints
(§1.5; PRD §3.5)."""

from flask import Blueprint, request

from db import db
from errors import err, ERR_INVALID_REQUEST
from middleware import body, required, pagination, page
from response import ok, ok_list
from routes._shared import authed
from services import licensing, serialize

bp = Blueprint("licensing", __name__)
READ = ["Any"]
COORD = ["LicensingCoordinator"]


@bp.post("/agency/product-licenses")
@authed(COORD)
def create_license(user_id, role):
    data = body()
    row = licensing.create_license(data)
    return ok(serialize.license_(row), 201)


@bp.get("/agency/product-licenses/<license_id>")
@authed(READ)
def get_license(user_id, role, license_id):
    return ok(serialize.license_(licensing.get_license(license_id)))


@bp.post("/agency/product-licenses/<license_id>/activate")
@authed(COORD)
def activate_license(user_id, role, license_id):
    row = licensing.get_license(license_id)
    licensing.activate_license(row)
    return ok(serialize.license_(row))


@bp.post("/agency/product-licenses/<license_id>/renew")
@authed(COORD)
def renew_license(user_id, role, license_id):
    row = licensing.get_license(license_id)
    expires_at = body().get("expires_at")
    if expires_at is None:
        raise err(ERR_INVALID_REQUEST, "expires_at is required")
    licensing.renew_license(row, expires_at)
    return ok(serialize.license_(row))


@bp.get("/agency/product-licenses/<license_id>/carrier-appointments")
@authed(READ)
def license_appointments(user_id, role, license_id):
    licensing.get_license(license_id)
    limit, offset = pagination()
    status = request.args.get("appointment_status")
    items = [a for a in db.appointments.values()
             if a["requires_license_id"] == license_id
             and (status is None or a["appointment_status"] == status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.appointment(a) for a in selected], limit, offset, len(items))


# ---------------------------------------------------------------------------
# SecuritiesRegistration
# ---------------------------------------------------------------------------
@bp.post("/agency/securities-registrations")
@authed(COORD)
def create_registration(user_id, role):
    data = body()
    row = licensing.create_registration(data)
    return ok(serialize.registration(row), 201)


@bp.get("/agency/securities-registrations")
@authed(READ)
def list_registrations(user_id, role):
    limit, offset = pagination()
    filters = {
        "advisor_id": request.args.get("advisor_id"),
        "registration_type": request.args.get("registration_type"),
        "status": request.args.get("status"),
    }
    items = [r for r in db.registrations.values()
             if all(value is None or r.get(key) == value for key, value in filters.items())]
    selected = page(items, limit, offset)
    return ok_list([serialize.registration(r) for r in selected], limit, offset, len(items))


@bp.get("/agency/securities-registrations/<registration_id>")
@authed(READ)
def get_registration(user_id, role, registration_id):
    return ok(serialize.registration(licensing.get_registration(registration_id)))


@bp.post("/agency/securities-registrations/<registration_id>/activate")
@authed(COORD)
def activate_registration(user_id, role, registration_id):
    row = licensing.get_registration(registration_id)
    licensing.activate_registration(row)
    return ok(serialize.registration(row))


@bp.get("/agency/securities-registrations/<registration_id>/dependents")
@authed(READ)
def dependents(user_id, role, registration_id):
    row = licensing.get_registration(registration_id)
    limit, offset = pagination()
    status = request.args.get("status")
    items = [r for r in licensing.dependents(row)
             if status is None or r["status"] == status]
    selected = page(items, limit, offset)
    return ok_list([serialize.registration(r) for r in selected], limit, offset, len(items))


# ---------------------------------------------------------------------------
# CarrierAppointment
# ---------------------------------------------------------------------------
@bp.post("/agency/carrier-appointments")
@authed(COORD)
def create_appointment(user_id, role):
    data = body()
    row = licensing.create_appointment(data)
    return ok(serialize.appointment(row), 201)


@bp.get("/agency/carrier-appointments/<appointment_id>")
@authed(READ)
def get_appointment(user_id, role, appointment_id):
    return ok(serialize.appointment(licensing.get_appointment(appointment_id)))


@bp.post("/agency/carrier-appointments/<appointment_id>/approve")
@authed(COORD)
def approve(user_id, role, appointment_id):
    row = licensing.get_appointment(appointment_id)
    licensing.approve_appointment(row)
    return ok(serialize.appointment(row))


@bp.post("/agency/carrier-appointments/<appointment_id>/reject")
@authed(COORD)
def reject(user_id, role, appointment_id):
    row = licensing.get_appointment(appointment_id)
    licensing.reject_appointment(row)
    return ok(serialize.appointment(row))