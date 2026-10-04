"""Stores, hospital posture, members, pets, breed rules, bays and the clock."""

from flask import Blueprint, request

import db
import shapes
import validate
from errors import ApiError
from response import ok_array, ok_object
from services import core, store as svc

bp = Blueprint("stores", __name__)

READ_ANY = ("Any",)


def _page(query, rows, shaper):
    limit, offset = validate.paginate(query)
    window, total = core.page(rows, limit, offset)
    return ok_array([shaper(r) for r in window], limit, offset, total)


# --- stores -----------------------------------------------------------------

@bp.route("/stores", methods=["POST"])
def create_store():
    validate.check_profile(request.headers, ("PlatformAdmin",))
    body = validate.normalize(request.get_json(silent=True))
    row = svc.create_store(body)
    return ok_object(shapes.store(row), 201)


@bp.route("/stores", methods=["GET"])
def list_stores():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("stores", request.args, ["state_code"])
    return _page(request.args, rows, shapes.store)


@bp.route("/stores/<store_id>", methods=["GET"])
def read_store(store_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.store(svc.read_store(store_id)))


@bp.route("/stores/<store_id>/restrict", methods=["POST"])
def restrict(store_id):
    validate.check_profile(request.headers, ("PlatformAdmin",))
    row = svc.restrict(validate.normalize(request.get_json(silent=True)), store_id)
    return ok_object(shapes.store(row))


@bp.route("/stores/<store_id>/lift-posture-restriction", methods=["POST"])
def lift_restriction(store_id):
    validate.check_profile(request.headers, ("PlatformAdmin",))
    row = svc.lift_posture_restriction(
        validate.normalize(request.get_json(silent=True)), store_id)
    return ok_object(shapes.store(row))


@bp.route("/stores/<store_id>/freeze-hospital", methods=["POST"])
def freeze_hospital(store_id):
    validate.check_profile(request.headers, ("PlatformAdmin",))
    row = svc.freeze_hospital(validate.normalize(request.get_json(silent=True)), store_id)
    return ok_object(shapes.store(row))


@bp.route("/stores/<store_id>/reopen-hospital", methods=["POST"])
def reopen_hospital(store_id):
    validate.check_profile(request.headers, ("PlatformAdmin",))
    row = svc.reopen_hospital(validate.normalize(request.get_json(silent=True)), store_id)
    return ok_object(shapes.store(row))


@bp.route("/stores/<store_id>/_bump-occupancy-v1", methods=["POST"])
def bump_occupancy(store_id):
    validate.check_profile(request.headers, ("PlatformAdmin",))
    row = svc.bump_occupancy(validate.normalize(request.get_json(silent=True)), store_id)
    return ok_object(shapes.store(row))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    validate.check_profile(request.headers, ("PlatformAdmin",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(svc.set_clock(body))


# --- members ----------------------------------------------------------------

@bp.route("/stores/members", methods=["POST"])
def create_member():
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.member(svc.create_member(body)), 201)


@bp.route("/stores/members", methods=["GET"])
def list_members():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("members", request.args, ["home_store_id", "status"])
    return _page(request.args, rows, shapes.member)


@bp.route("/stores/members/<member_id>", methods=["GET"])
def read_member(member_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.member(core.require_member(member_id)))


@bp.route("/stores/members/<member_id>/activate", methods=["POST"])
def activate_member(member_id):
    validate.check_profile(request.headers, ("StoreManager",))
    return ok_object(shapes.member(svc.set_member_status(
        member_id, "ACTIVE", validate.normalize(request.get_json(silent=True)))))


@bp.route("/stores/members/<member_id>/suspend", methods=["POST"])
def suspend_member(member_id):
    validate.check_profile(request.headers, ("StoreManager",))
    return ok_object(shapes.member(svc.set_member_status(
        member_id, "SUSPENDED", validate.normalize(request.get_json(silent=True)))))


@bp.route("/stores/members/<member_id>/archive", methods=["POST"])
def archive_member(member_id):
    validate.check_profile(request.headers, ("StoreManager",))
    return ok_object(shapes.member(svc.archive_member(
        member_id, validate.normalize(request.get_json(silent=True)))))


@bp.route("/stores/members/<member_id>/pets", methods=["GET"])
def list_member_pets(member_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_member(member_id)
    rows = [p for p in db.rows("pets") if p["member_id"] == member_id]
    return _page(request.args, rows, shapes.pet_finalized)


# --- pets -------------------------------------------------------------------

@bp.route("/stores/pets", methods=["POST"])
def create_pet():
    validate.check_profile(request.headers, ("GroomingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.pet(svc.create_pet(body)), 201)


@bp.route("/stores/pets", methods=["GET"])
def list_pets():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("pets", request.args, ["member_id", "status"])
    return _page(request.args, rows, shapes.pet_finalized)


@bp.route("/stores/pets/<pet_id>", methods=["GET"])
def read_pet(pet_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.pet_finalized(core.require_pet(pet_id)))


@bp.route("/stores/pets/<pet_id>/archive", methods=["POST"])
def archive_pet(pet_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.pet(svc.archive_pet(body, pet_id)))


@bp.route("/stores/pets/<pet_id>/incident-records", methods=["GET"])
def pet_incidents(pet_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_pet(pet_id)
    rows = core.pet_incidents(pet_id)
    return _page(request.args, rows, shapes.incident)


@bp.route("/stores/pets/<pet_id>/rabies-certificates", methods=["GET"])
def pet_certificates(pet_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_pet(pet_id)
    rows = [c for c in db.rows("certificates") if c["pet_id"] == pet_id]
    return _page(request.args, rows, shapes.certificate)


@bp.route("/stores/pets/<pet_id>/veterinary-encounters", methods=["GET"])
def pet_encounters(pet_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_pet(pet_id)
    rows = [e for e in db.rows("encounters") if e["pet_id"] == pet_id]
    return _page(request.args, rows, shapes.encounter)


@bp.route("/stores/pets/<pet_id>/prescription-authorizations", methods=["GET"])
def pet_authorizations(pet_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_pet(pet_id)
    rows = [a for a in db.rows("authorizations") if a["pet_id"] == pet_id]
    return _page(request.args, rows, shapes.authorization)


# --- breed handling rules ---------------------------------------------------

@bp.route("/breed-handling-rules", methods=["POST"])
def create_rule():
    validate.check_profile(request.headers, ("PlatformAdmin",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.breed_rule(svc.create_breed_rule(body)), 201)


@bp.route("/breed-handling-rules", methods=["GET"])
def list_rules():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("breed_rules", request.args, ["species"])
    return _page(request.args, rows, shapes.breed_rule)


@bp.route("/breed-handling-rules/<rule_id>", methods=["GET"])
def read_rule(rule_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.breed_rule(core.require_rule(rule_id)))


# --- service bays -----------------------------------------------------------

@bp.route("/stores/<store_id>/service-bays", methods=["POST"])
def create_bay(store_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.bay(svc.create_bay(body, store_id)), 201)


@bp.route("/stores/<store_id>/service-bays/<bay_id>", methods=["GET"])
def read_bay(store_id, bay_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_store(store_id)
    bay = core.require_bay(bay_id)
    if bay["store_id"] != store_id:
        raise ApiError("ERR_SERVICE_BAY_NOT_FOUND")
    return ok_object(shapes.bay(bay))


@bp.route("/stores/<store_id>/service-bays/<bay_id>/disable", methods=["POST"])
def disable_bay(store_id, bay_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.bay(svc.disable_bay(body, store_id, bay_id)))


@bp.route("/stores/service-bays", methods=["GET"])
def list_bays():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("bays", request.args, ["store_id", "status"])
    return _page(request.args, rows, shapes.bay)


@bp.route("/stores/service-bays/<bay_id>", methods=["GET"])
def read_bay_by_id(bay_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.bay(core.require_bay(bay_id)))