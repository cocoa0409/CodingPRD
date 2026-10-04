"""Guided exercise sessions, outreach contacts, clinicians and consults."""

from flask import Blueprint

from db import STORE
from middleware import body, query, require
from response import array_response, object_response, page
from services import intake, operations

bp = Blueprint("sessions", __name__)


# --- exercise sessions -----------------------------------------------------
@bp.route("/msk/enrollments/<enrollment_id>/sessions", methods=["POST"])
def book_session(enrollment_id):
    require(["EnrollmentOps"], "POST /msk/enrollments/{id}/sessions")
    return object_response(
        dict(operations.book_session(enrollment_id, body())), 201
    )


@bp.route("/msk/exercise-sessions", methods=["GET"])
def list_sessions():
    require(["EnrollmentOps", "ClinicalOps", "Member"], "GET /msk/exercise-sessions")
    rows = STORE.all("ExerciseSession")
    enrollment_id = query("enrollment_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    status = query("session_status")
    if status:
        rows = [r for r in rows if r["session_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/exercise-sessions/<session_id>", methods=["GET"])
def read_session(session_id):
    require(
        ["EnrollmentOps", "ClinicalOps", "Member"], "GET /msk/exercise-sessions/{id}"
    )
    row = STORE.need("ExerciseSession", session_id, "ExerciseSession")
    return object_response(dict(row))


@bp.route("/msk/exercise-sessions/<session_id>/complete", methods=["POST"])
def complete_session(session_id):
    user_id, role = require(
        ["Member"], "POST /msk/exercise-sessions/{id}/complete"
    )
    return object_response(
        dict(operations.complete_session(session_id, body(), user_id))
    )


@bp.route("/msk/exercise-sessions/<session_id>/weekly-transition", methods=["POST"])
def weekly_transition(session_id):
    require(
        ["EligibilityService"],
        "POST /msk/exercise-sessions/{id}/weekly-transition",
    )
    return object_response(
        dict(operations.weekly_transition(session_id, body()))
    )


# --- outreach contacts -----------------------------------------------------
@bp.route("/msk/outreach-contacts", methods=["POST"])
def queue_outreach():
    require(["OutreachService"], "POST /msk/outreach-contacts")
    return object_response(dict(operations.queue_outreach(body())), 201)


@bp.route("/msk/outreach-contacts", methods=["GET"])
def list_outreach():
    require(["OutreachService", "EnrollmentOps"], "GET /msk/outreach-contacts")
    rows = STORE.all("OutreachContact")
    enrollment_id = query("enrollment_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    status = query("outreach_status")
    if status:
        rows = [r for r in rows if r["outreach_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/outreach-contacts/<contact_id>", methods=["GET"])
def read_outreach(contact_id):
    require(["OutreachService", "EnrollmentOps"], "GET /msk/outreach-contacts/{id}")
    row = STORE.need("OutreachContact", contact_id, "OutreachContact")
    return object_response(dict(row))


@bp.route("/msk/outreach-contacts/<contact_id>/deliver", methods=["POST"])
def deliver_outreach(contact_id):
    require(["OutreachService"], "POST /msk/outreach-contacts/{id}/deliver")
    return object_response(dict(operations.deliver_outreach(contact_id)))


# --- clinicians ------------------------------------------------------------
@bp.route("/msk/clinicians", methods=["POST"])
def create_clinician():
    require(["ClinicalOps"], "POST /msk/clinicians")
    return object_response(dict(operations.create_clinician(body())), 201)


@bp.route("/msk/clinicians", methods=["GET"])
def list_clinicians():
    require(["ClinicalOps", "EnrollmentOps", "BillingOps"], "GET /msk/clinicians")
    rows = STORE.all("Clinician")
    discipline = query("discipline")
    if discipline:
        rows = [r for r in rows if r["discipline"] == discipline]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/clinicians/<clinician_id>", methods=["GET"])
def read_clinician(clinician_id):
    require(["ClinicalOps", "EnrollmentOps", "BillingOps"], "GET /msk/clinicians/{id}")
    row = STORE.need("Clinician", clinician_id, "Clinician")
    return object_response(dict(row))


@bp.route("/msk/clinicians/<clinician_id>/limit", methods=["POST"])
def limit_clinician(clinician_id):
    require(["ClinicalOps"], "POST /msk/clinicians/{id}/limit")
    return object_response(dict(operations.limit_clinician(clinician_id)))


@bp.route("/msk/clinicians/<clinician_id>/restore", methods=["POST"])
def restore_clinician(clinician_id):
    require(["ClinicalOps"], "POST /msk/clinicians/{id}/restore")
    return object_response(dict(operations.restore_clinician(clinician_id)))


@bp.route("/msk/clinicians/<clinician_id>/deactivate", methods=["POST"])
def deactivate_clinician(clinician_id):
    require(["ClinicalOps"], "POST /msk/clinicians/{id}/deactivate")
    return object_response(dict(operations.deactivate_clinician(clinician_id)))


# --- appointments ----------------------------------------------------------
@bp.route("/msk/appointments", methods=["POST"])
def book_appointment():
    require(["EnrollmentOps"], "POST /msk/appointments")
    return object_response(dict(operations.book_appointment(body())), 201)


@bp.route("/msk/appointments", methods=["GET"])
def list_appointments():
    require(
        ["EnrollmentOps", "ClinicalOps", "Clinician"], "GET /msk/appointments"
    )
    rows = STORE.all("Appointment")
    enrollment_id = query("enrollment_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    clinician_id = query("clinician_id")
    if clinician_id:
        rows = [r for r in rows if r["clinician_id"] == clinician_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/appointments/<appointment_id>", methods=["GET"])
def read_appointment(appointment_id):
    require(
        ["EnrollmentOps", "ClinicalOps", "Clinician"], "GET /msk/appointments/{id}"
    )
    row = STORE.need("Appointment", appointment_id, "Appointment")
    return object_response(dict(row))


@bp.route("/msk/appointments/<appointment_id>/cancel", methods=["POST"])
def cancel_appointment(appointment_id):
    require(
        ["Clinician", "EnrollmentOps"], "POST /msk/appointments/{id}/cancel"
    )
    return object_response(dict(operations.cancel_appointment(appointment_id)))


@bp.route("/msk/appointments/<appointment_id>/complete", methods=["POST"])
def complete_appointment(appointment_id):
    require(["Clinician"], "POST /msk/appointments/{id}/complete")
    return object_response(dict(operations.complete_appointment(appointment_id)))