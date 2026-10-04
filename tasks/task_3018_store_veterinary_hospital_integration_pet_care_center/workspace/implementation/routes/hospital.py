"""Veterinary encounters, prescriptions, pharmacy handoffs and cross-sells."""

from flask import Blueprint, request

import db
import shapes
import validate
from response import ok_array, ok_object
from services import core, hospital as svc, store as stores_svc

bp = Blueprint("hospital", __name__)
READ_ANY = ("Any",)


def _page(query, rows, shaper):
    limit, offset = validate.paginate(query)
    window, total = core.page(rows, limit, offset)
    return ok_array([shaper(r) for r in window], limit, offset, total)


# --- encounters -------------------------------------------------------------

@bp.route("/stores/<store_id>/veterinary-encounters", methods=["POST"])
def create_encounter(store_id):
    validate.check_profile(request.headers, ("VeterinaryStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.encounter(svc.create_encounter(body, store_id)), 201)


@bp.route("/stores/veterinary-encounters", methods=["GET"])
def list_encounters():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("encounters", request.args,
                         ["store_id", "pet_id", "booking_id", "status"])
    return _page(request.args, rows, shapes.encounter)


@bp.route("/stores/veterinary-encounters/<encounter_id>", methods=["GET"])
def read_encounter(encounter_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.encounter(core.require_encounter(encounter_id)))


@bp.route("/stores/retail/veterinary-encounters/<encounter_id>", methods=["GET"])
def read_encounter_retail(encounter_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.encounter(core.require_encounter(encounter_id), retail=True))


@bp.route("/stores/<store_id>/veterinary-encounters/<encounter_id>/check-in", methods=["POST"])
def check_in(store_id, encounter_id):
    validate.check_profile(request.headers, ("VeterinaryStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.encounter(svc.check_in(body, store_id, encounter_id)))


@bp.route("/stores/<store_id>/veterinary-encounters/<encounter_id>/start-exam", methods=["POST"])
def start_exam(store_id, encounter_id):
    validate.check_profile(request.headers, ("VeterinaryStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.encounter(svc.start_exam(body, store_id, encounter_id)))


@bp.route("/stores/<store_id>/veterinary-encounters/<encounter_id>/complete-exam", methods=["POST"])
def complete_exam(store_id, encounter_id):
    validate.check_profile(request.headers, ("VeterinaryStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.encounter(svc.complete_exam(body, store_id, encounter_id)))


@bp.route("/stores/<store_id>/veterinary-encounters/<encounter_id>/cancel", methods=["POST"])
def cancel_encounter(store_id, encounter_id):
    validate.check_profile(request.headers, ("VeterinaryStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.encounter(svc.cancel_encounter(body, store_id, encounter_id)))


@bp.route("/stores/<store_id>/veterinary-encounters/<encounter_id>/charge-summary", methods=["GET"])
def charge_summary(store_id, encounter_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(svc.charge_summary(store_id, encounter_id))


@bp.route("/stores/<store_id>/veterinary-encounters/<encounter_id>/prescription-authorizations", methods=["GET"])
def encounter_authorizations(store_id, encounter_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_store(store_id)
    core.require_encounter(encounter_id)
    rows = core.encounter_authorizations(encounter_id)
    return _page(request.args, rows, shapes.authorization)


# --- prescriptions ----------------------------------------------------------

@bp.route("/stores/<store_id>/prescription-authorizations", methods=["POST"])
def create_authorization(store_id):
    validate.check_profile(request.headers, ("VeterinaryStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.authorization(
        svc.create_authorization(body, store_id)), 201)


@bp.route("/stores/prescription-authorizations", methods=["GET"])
def list_authorizations():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("authorizations", request.args,
                         ["store_id", "pet_id", "encounter_id", "sku", "status"])
    return _page(request.args, rows, shapes.authorization)


@bp.route("/stores/prescription-authorizations/<authorization_id>", methods=["GET"])
def read_authorization(authorization_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.authorization(core.require_authorization(authorization_id)))


@bp.route("/stores/<store_id>/prescription-authorizations/<authorization_id>/revoke", methods=["POST"])
def revoke_authorization(store_id, authorization_id):
    validate.check_profile(request.headers, ("VeterinaryStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.authorization(
        svc.revoke_authorization(body, store_id, authorization_id)))


# --- pharmacy orders --------------------------------------------------------

@bp.route("/stores/<store_id>/pharmacy-orders", methods=["POST"])
def create_order(store_id):
    validate.check_profile(request.headers, ("PharmacyStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.pharmacy_order(svc.create_order(body, store_id)), 201)


@bp.route("/stores/pharmacy-orders", methods=["GET"])
def list_orders():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("pharmacy_orders", request.args,
                         ["authorization_id", "store_id", "status"])
    return _page(request.args, rows, shapes.pharmacy_order)


@bp.route("/stores/pharmacy-orders/<order_id>", methods=["GET"])
def read_order(order_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.pharmacy_order(core.require_order(order_id)))


@bp.route("/stores/<store_id>/pharmacy-orders/<order_id>/dispense", methods=["POST"])
def dispense_order(store_id, order_id):
    validate.check_profile(request.headers, ("PharmacyStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.pharmacy_order(svc.dispense_order(body, store_id, order_id)))


@bp.route("/stores/<store_id>/pharmacy-orders/<order_id>/reject", methods=["POST"])
def reject_order(store_id, order_id):
    validate.check_profile(request.headers, ("PharmacyStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.pharmacy_order(svc.reject_order(body, store_id, order_id)))


@bp.route("/stores/prescription-authorizations/<authorization_id>/pharmacy-orders", methods=["GET"])
def authorization_orders(authorization_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_authorization(authorization_id)
    rows = core.authorization_orders(authorization_id)
    return _page(request.args, rows, shapes.pharmacy_order)


# --- retail cross-sells -----------------------------------------------------

@bp.route("/stores/<store_id>/retail-cross-sells", methods=["POST"])
def create_cross_sell(store_id):
    validate.check_profile(request.headers, ("PharmacyStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.cross_sell(
        stores_svc.create_cross_sell(body, store_id)), 201)


@bp.route("/stores/retail-cross-sells", methods=["GET"])
def list_cross_sells():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("cross_sells", request.args,
                         ["store_id", "authorization_id", "pet_id", "status"])
    return _page(request.args, rows, shapes.cross_sell)


@bp.route("/stores/retail-cross-sells/<cross_sell_id>", methods=["GET"])
def read_cross_sell(cross_sell_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.cross_sell(core.require_cross_sell(cross_sell_id)))


@bp.route("/stores/<store_id>/retail-cross-sells/<cross_sell_id>/redeem", methods=["POST"])
def redeem_cross_sell(store_id, cross_sell_id):
    validate.check_profile(request.headers, ("PharmacyStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.cross_sell(
        stores_svc.redeem_cross_sell(body, store_id, cross_sell_id)))


@bp.route("/stores/prescription-authorizations/<authorization_id>/retail-cross-sells", methods=["GET"])
def authorization_cross_sells(authorization_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_authorization(authorization_id)
    rows = [c for c in db.rows("cross_sells") if c["authorization_id"] == authorization_id]
    return _page(request.args, rows, shapes.cross_sell)