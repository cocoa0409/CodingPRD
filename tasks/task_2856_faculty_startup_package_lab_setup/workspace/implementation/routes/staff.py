"""Lab staff and graduate appointments (PRD 3.8)."""

from datetime import date

from flask import Blueprint

import authz
import cascades
import derive
import envelope
import ledger
import lookups
import serialize
import store
import validate
from errors import fail

bp = Blueprint("staff", __name__)

APPOINTMENT_TYPES = ("LAB_MANAGER", "POSTDOC", "GRAD_RA", "TECHNICIAN")

READ_ROLES = (
    authz.ROLE_DEAN_OFFICE,
    authz.ROLE_DEAN,
    authz.ROLE_DEPARTMENT_CHAIR,
    authz.ROLE_FACULTY,
)


@bp.post("/staff-appointments")
def create_appointment():
    act = authz.actor((authz.ROLE_DEAN_OFFICE, authz.ROLE_FACULTY))
    payload = validate.body()
    package_id = validate.identifier(payload, "package_id")
    appointment_type = validate.enum(payload, "appointment_type", APPOINTMENT_TYPES)
    fte = validate.number(payload, "fte", exclusive_min=0, maximum=1)
    monthly_cost = validate.cents(payload, "monthly_cost_cents", positive=True)
    start_date = validate.calendar_date(payload, "start_date")
    end_date = validate.calendar_date(payload, "end_date")
    validate.date_at_or_before(
        start_date, end_date, "end_date must be at or after start_date"
    )
    package = lookups.get_package(package_id)
    authz.faculty_scope(act, package["faculty_id"])
    record = {
        "id": store.new_id(),
        "package_id": package["id"],
        "appointment_type": appointment_type,
        "fte": fte,
        "monthly_cost_cents": monthly_cost,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "status": "PROPOSED",
        "committed_months": derive.month_span(start_date, end_date),
        "ended_on": None,
    }
    store.stamp_new(record)
    store.db.staff_appointments[record["id"]] = record
    return envelope.created(serialize.staff_appointment(record))


@bp.post("/staff-appointments/<appointment_id>/activate")
def activate_appointment(appointment_id):
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    record = lookups.get_appointment(appointment_id)
    package = store.db.packages.get(record["package_id"])
    if package is None:
        fail("ERR_PACKAGE_NOT_FOUND", "the funding package no longer exists")
    if package["spend_status"] != "SPENDING":
        fail(
            "ERR_PACKAGE_SPEND_FROZEN",
            "the funding package is not in spend_status SPENDING",
        )
    if record["status"] != "PROPOSED":
        fail(
            "ERR_SPEND_ITEM_STATE_INVALID",
            "only a PROPOSED appointment may be activated",
        )
    record_faculty = store.db.faculty.get(package["faculty_id"])
    if record_faculty is None or record_faculty["appointment_status"] != "ACTIVE":
        fail("ERR_FACULTY_NOT_ACTIVE", "the package's faculty member must be ACTIVE")
    total = derive.encumbrance_total_cents(record)
    ledger.check_waterfall(package, "PERSONNEL", total)
    record["status"] = "ACTIVE"
    store.touch(record)
    ledger.run_waterfall(
        package,
        "PERSONNEL",
        total,
        ledger.SOURCE_STAFF_APPOINTMENT,
        record["id"],
        "staff appointment activated",
    )
    return envelope.object_response(serialize.staff_appointment(record))


@bp.post("/staff-appointments/<appointment_id>/end")
def end_appointment(appointment_id):
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    payload = validate.body()
    end_date = validate.calendar_date(payload, "end_date")
    record = lookups.get_appointment(appointment_id)
    package = store.db.packages.get(record["package_id"])
    if package is None:
        fail("ERR_PACKAGE_NOT_FOUND", "the funding package no longer exists")
    if end_date < date.fromisoformat(record["start_date"]):
        fail(
            "ERR_VALIDATION",
            "end_date must be at or after the appointment's start_date",
        )
    if record["status"] != "ACTIVE":
        fail("ERR_SPEND_ITEM_STATE_INVALID", "only an ACTIVE appointment may be ended")
    cascades.end_appointment(record, package, end_date)
    return envelope.object_response(serialize.staff_appointment(record))


@bp.get("/staff-appointments/<appointment_id>")
def read_appointment(appointment_id):
    act = authz.actor(READ_ROLES)
    record = lookups.get_appointment(appointment_id)
    package = store.db.packages.get(record["package_id"])
    if package is not None:
        authz.faculty_scope(act, package["faculty_id"])
    return envelope.object_response(serialize.staff_appointment(record))
