"""Vaccination clinics, walk-in visits, certificates and state reporting."""

from flask import Blueprint, request

import db
import shapes
import validate
from errors import ApiError
from response import ok_array, ok_object
from services import core, clinic as svc

bp = Blueprint("clinics", __name__)
READ_ANY = ("Any",)


def _page(query, rows, shaper):
    limit, offset = validate.paginate(query)
    window, total = core.page(rows, limit, offset)
    return ok_array([shaper(r) for r in window], limit, offset, total)


@bp.route("/stores/<store_id>/vaccination-clinics", methods=["POST"])
def create_clinic(store_id):
    validate.check_profile(request.headers, ("VaccinationStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.clinic(svc.create_clinic(body, store_id)), 201)


@bp.route("/stores/vaccination-clinics", methods=["GET"])
def list_clinics():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("clinics", request.args, ["store_id", "clinic_status"])
    return _page(request.args, rows, shapes.clinic)


@bp.route("/stores/vaccination-clinics/<clinic_id>", methods=["GET"])
def read_clinic(clinic_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.clinic(core.require_clinic(clinic_id)))


@bp.route("/stores/<store_id>/vaccination-clinics/<clinic_id>/open-walk-ins", methods=["POST"])
def open_walk_ins(store_id, clinic_id):
    validate.check_profile(request.headers, ("VaccinationStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.clinic(svc.open_walk_ins(body, store_id, clinic_id)))


@bp.route("/stores/<store_id>/vaccination-clinics/<clinic_id>/close-walk-ins", methods=["POST"])
def close_walk_ins(store_id, clinic_id):
    validate.check_profile(request.headers, ("VaccinationStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.clinic(svc.close_walk_ins(body, store_id, clinic_id)))


@bp.route("/stores/<store_id>/vaccination-clinics/<clinic_id>/coverage", methods=["POST"])
def set_coverage(store_id, clinic_id):
    """Record the relief veterinarian the creation-time staffing decision demands."""
    validate.check_profile(request.headers, ("VaccinationStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.clinic(svc.set_coverage_provider(body, store_id, clinic_id)))


@bp.route("/stores/<store_id>/vaccination-clinics/<clinic_id>/vaccination-visits", methods=["GET"])
def clinic_visits(store_id, clinic_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_store(store_id)
    clinic = core.require_clinic(clinic_id)
    if clinic["store_id"] != store_id:
        raise ApiError("ERR_CLINIC_NOT_FOUND")
    rows = [v for v in db.rows("visits") if v["clinic_id"] == clinic_id]
    return _page(request.args, rows, shapes.visit)


@bp.route("/stores/<store_id>/vaccination-clinics/<clinic_id>/state-report", methods=["GET"])
def state_report(store_id, clinic_id):
    validate.check_profile(request.headers, ("ComplianceOfficer",))
    return ok_object(svc.state_report(clinic_id, store_id))


# --- visits -----------------------------------------------------------------

@bp.route("/stores/<store_id>/vaccination-visits", methods=["POST"])
def create_visit(store_id):
    validate.check_profile(request.headers, ("VaccinationStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.visit(svc.create_visit(body, store_id)), 201)


@bp.route("/stores/vaccination-visits", methods=["GET"])
def list_visits():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("visits", request.args,
                         ["clinic_id", "pet_id", "status", "store_id"])
    return _page(request.args, rows, shapes.visit)


@bp.route("/stores/vaccination-visits/<visit_id>", methods=["GET"])
def read_visit(visit_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.visit(core.require_visit(visit_id)))


@bp.route("/stores/<store_id>/vaccination-visits/<visit_id>/issue-certificate", methods=["POST"])
def issue_certificate(store_id, visit_id):
    validate.check_profile(request.headers, ("VaccinationStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.visit(svc.issue_certificate(body, store_id, visit_id)))


@bp.route("/stores/<store_id>/vaccination-visits/<visit_id>/submit-state-report", methods=["POST"])
def submit_state_report(store_id, visit_id):
    validate.check_profile(request.headers, ("ComplianceOfficer",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.visit(svc.submit_state_report(body, store_id, visit_id)))


@bp.route("/stores/vaccination-visits/<visit_id>/rabies-certificate", methods=["GET"])
def visit_certificate(visit_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_visit(visit_id)
    rows = [c for c in db.rows("certificates") if c["visit_id"] == visit_id]
    return _page(request.args, rows, shapes.certificate)


# --- certificates -----------------------------------------------------------

@bp.route("/stores/rabies-certificates", methods=["GET"])
def list_certificates():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("certificates", request.args,
                         ["visit_id", "pet_id", "store_id"])
    return _page(request.args, rows, shapes.certificate)


@bp.route("/stores/rabies-certificates/<certificate_id>", methods=["GET"])
def read_certificate(certificate_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.certificate(core.require_certificate(certificate_id)))