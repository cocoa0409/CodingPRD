"""Service bookings, grooming risk screenings and incident records."""

from flask import Blueprint, request

import db
import shapes
import validate
from response import ok_array, ok_object
from services import core, booking as svc, incident as incidents

bp = Blueprint("bookings", __name__)
READ_ANY = ("Any",)


def _page(query, rows, shaper):
    limit, offset = validate.paginate(query)
    window, total = core.page(rows, limit, offset)
    return ok_array([shaper(r) for r in window], limit, offset, total)


@bp.route("/stores/<store_id>/service-bookings", methods=["POST"])
def create_booking(store_id):
    validate.check_profile(request.headers, ("GroomingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.booking(svc.create(body, store_id)), 201)


@bp.route("/stores/service-bookings/<booking_id>", methods=["GET"])
def read_booking(booking_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.booking(svc.read(booking_id)))


@bp.route("/stores/service-bookings", methods=["GET"])
def list_bookings():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("bookings", request.args,
                         ["store_id", "bay_id", "pet_id", "status"])
    return _page(request.args, rows, shapes.booking)


@bp.route("/stores/<store_id>/service-bookings/<booking_id>/screen", methods=["POST"])
def screen(store_id, booking_id):
    validate.check_profile(request.headers, ("GroomingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.booking(svc.screen(body, store_id, booking_id)))


@bp.route("/stores/<store_id>/service-bookings/<booking_id>/confirm-bay", methods=["POST"])
def confirm_bay(store_id, booking_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.booking(svc.confirm_bay(body, store_id, booking_id)))


@bp.route("/stores/<store_id>/service-bookings/<booking_id>/start-service", methods=["POST"])
def start_service(store_id, booking_id):
    validate.check_profile(request.headers, ("GroomingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.booking(svc.start_service(body, store_id, booking_id)))


@bp.route("/stores/<store_id>/service-bookings/<booking_id>/complete-service", methods=["POST"])
def complete_service(store_id, booking_id):
    validate.check_profile(request.headers, ("GroomingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.booking(svc.complete_service(body, store_id, booking_id)))


@bp.route("/stores/<store_id>/service-bookings/<booking_id>/mark-no-show", methods=["POST"])
def mark_no_show(store_id, booking_id):
    validate.check_profile(request.headers, ("GroomingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.booking(svc.mark_no_show(body, store_id, booking_id)))


@bp.route("/stores/<store_id>/service-bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(store_id, booking_id):
    validate.check_profile(request.headers, ("GroomingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.booking(svc.cancel(body, store_id, booking_id)))


@bp.route("/stores/<store_id>/service-bookings/<booking_id>/risk-screenings", methods=["GET"])
def booking_screenings(store_id, booking_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_store(store_id)
    core.require_booking(booking_id)
    rows = [s for s in db.rows("screenings") if s["booking_id"] == booking_id]
    return _page(request.args, rows, shapes.screening)


@bp.route("/stores/risk-screenings", methods=["GET"])
def list_screenings():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("screenings", request.args, ["booking_id"])
    return _page(request.args, rows, shapes.screening)


@bp.route("/stores/risk-screenings/<screening_id>", methods=["GET"])
def read_screening(screening_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.screening(core.require_screening(screening_id)))


# --- incident records -------------------------------------------------------

@bp.route("/stores/<store_id>/incident-records", methods=["POST"])
def create_incident(store_id):
    validate.check_profile(request.headers, ("GroomingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.incident(incidents.create(body, store_id)), 201)


@bp.route("/stores/incident-records", methods=["GET"])
def list_incidents():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("incidents", request.args,
                         ["store_id", "booking_id", "pet_id", "claim_status"])
    return _page(request.args, rows, shapes.incident)


@bp.route("/stores/incident-records/<incident_id>", methods=["GET"])
def read_incident(incident_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.incident(core.require_incident(incident_id)))


@bp.route("/stores/<store_id>/incident-records/<incident_id>/begin-review", methods=["POST"])
def begin_review(store_id, incident_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.incident(
        incidents.begin_review(body, store_id, incident_id)))


@bp.route("/stores/<store_id>/incident-records/<incident_id>/approve-claim", methods=["POST"])
def approve_claim(store_id, incident_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.incident(
        incidents.approve_claim(body, store_id, incident_id)))


@bp.route("/stores/<store_id>/incident-records/<incident_id>/deny-claim", methods=["POST"])
def deny_claim(store_id, incident_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.incident(incidents.deny_claim(body, store_id, incident_id)))


@bp.route("/stores/<store_id>/incident-records/<incident_id>/return-to-queue", methods=["POST"])
def return_to_queue(store_id, incident_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.incident(
        incidents.return_to_queue(body, store_id, incident_id)))


@bp.route("/stores/<store_id>/incident-records/<incident_id>/claim-summary", methods=["GET"])
def claim_summary(store_id, incident_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(incidents.claim_summary(store_id, incident_id))


@bp.route("/stores/<store_id>/service-bookings/<booking_id>/incident-records", methods=["GET"])
def booking_incidents(store_id, booking_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_store(store_id)
    core.require_booking(booking_id)
    rows = core.booking_incidents(booking_id)
    return _page(request.args, rows, shapes.incident)