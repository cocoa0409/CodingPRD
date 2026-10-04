"""Membership packages, billing cycles and training enrollments."""

from flask import Blueprint, request

import shapes
import validate
from errors import ApiError
from response import ok_array, ok_object
from services import core, package as svc

bp = Blueprint("packages", __name__)
READ_ANY = ("Any",)


def _page(query, rows, shaper):
    limit, offset = validate.paginate(query)
    window, total = core.page(rows, limit, offset)
    return ok_array([shaper(r) for r in window], limit, offset, total)


# --- packages ---------------------------------------------------------------

@bp.route("/stores/<store_id>/members/<member_id>/service-packages", methods=["POST"])
def create_package(store_id, member_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.package(svc.create(body, store_id, member_id)), 201)


@bp.route("/stores/service-packages", methods=["GET"])
def list_packages():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("packages", request.args, ["member_id", "status"])
    return _page(request.args, rows, shapes.package)


@bp.route("/stores/service-packages/<package_id>", methods=["GET"])
def read_package(package_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.package(core.require_package(package_id)))


@bp.route("/stores/members/<member_id>/service-packages", methods=["GET"])
def member_packages(member_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_member(member_id)
    rows = core.member_packages(member_id)
    if request.args.get("status"):
        rows = [r for r in rows if r["status"] == request.args["status"]]
    return _page(request.args, rows, shapes.package)


@bp.route("/stores/<store_id>/members/<member_id>/service-packages/<package_id>/billing-cycles", methods=["POST"])
def advance_cycle(store_id, member_id, package_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.cycle(svc.advance_cycle(body, store_id, member_id, package_id)))


@bp.route("/stores/service-packages/<package_id>/billing-cycles", methods=["GET"])
def package_cycles(package_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_package(package_id)
    rows = core.package_cycles(package_id)
    if request.args.get("status"):
        rows = [r for r in rows if r["status"] == request.args["status"]]
    return _page(request.args, rows, shapes.cycle)


@bp.route("/stores/billing-cycles", methods=["GET"])
def list_cycles():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("cycles", request.args, ["package_id", "status"])
    return _page(request.args, rows, shapes.cycle)


@bp.route("/stores/billing-cycles/<cycle_id>", methods=["GET"])
def read_cycle(cycle_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.cycle(core.require_cycle(cycle_id)))


@bp.route("/stores/<store_id>/members/<member_id>/service-packages/<package_id>/pause", methods=["POST"])
def pause_package(store_id, member_id, package_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.package(svc.pause(body, store_id, member_id, package_id)))


@bp.route("/stores/<store_id>/members/<member_id>/service-packages/<package_id>/resume", methods=["POST"])
def resume_package(store_id, member_id, package_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.package(svc.resume(body, store_id, member_id, package_id)))


@bp.route("/stores/<store_id>/members/<member_id>/service-packages/<package_id>/cancel", methods=["POST"])
def cancel_package(store_id, member_id, package_id):
    validate.check_profile(request.headers, ("StoreManager",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.package(svc.cancel(body, store_id, member_id, package_id)))


# --- training enrollments ---------------------------------------------------

@bp.route("/stores/<store_id>/training-enrollments", methods=["POST"])
def create_enrollment(store_id):
    validate.check_profile(request.headers, ("TrainingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.enrollment(svc.create_enrollment(body, store_id)), 201)


@bp.route("/stores/training-enrollments", methods=["GET"])
def list_enrollments():
    validate.check_profile(request.headers, READ_ANY)
    rows = core.filtered("enrollments", request.args,
                         ["package_id", "store_id", "pet_id", "status"])
    return _page(request.args, rows, shapes.enrollment)


@bp.route("/stores/training-enrollments/<enrollment_id>", methods=["GET"])
def read_enrollment(enrollment_id):
    validate.check_profile(request.headers, READ_ANY)
    return ok_object(shapes.enrollment(core.require_enrollment(enrollment_id)))


@bp.route("/stores/<store_id>/training-enrollments/<enrollment_id>", methods=["GET"])
def read_store_enrollment(store_id, enrollment_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_store(store_id)
    enrollment = core.require_enrollment(enrollment_id)
    if enrollment["store_id"] != store_id:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND")
    return ok_object(shapes.enrollment(enrollment))


@bp.route("/stores/<store_id>/training-enrollments/<enrollment_id>/begin-course", methods=["POST"])
def begin_course(store_id, enrollment_id):
    validate.check_profile(request.headers, ("TrainingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.enrollment(
        svc.begin_course(body, store_id, enrollment_id)))


@bp.route("/stores/<store_id>/training-enrollments/<enrollment_id>/return-to-ack", methods=["POST"])
def return_to_ack(store_id, enrollment_id):
    validate.check_profile(request.headers, ("TrainingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.enrollment(
        svc.return_to_ack(body, store_id, enrollment_id)))


@bp.route("/stores/<store_id>/training-enrollments/<enrollment_id>/start-course", methods=["POST"])
def start_course(store_id, enrollment_id):
    validate.check_profile(request.headers, ("TrainingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.enrollment(
        svc.start_course(body, store_id, enrollment_id)))


@bp.route("/stores/<store_id>/training-enrollments/<enrollment_id>/revert-course", methods=["POST"])
def revert_course(store_id, enrollment_id):
    validate.check_profile(request.headers, ("TrainingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.enrollment(
        svc.revert_course(body, store_id, enrollment_id)))


@bp.route("/stores/<store_id>/training-enrollments/<enrollment_id>/record-progress", methods=["POST"])
def record_progress(store_id, enrollment_id):
    validate.check_profile(request.headers, ("TrainingStaff",))
    body = validate.normalize(request.get_json(silent=True))
    return ok_object(shapes.enrollment(
        svc.record_progress(body, store_id, enrollment_id)))


@bp.route("/stores/service-packages/<package_id>/training-enrollments", methods=["GET"])
def package_enrollments(package_id):
    validate.check_profile(request.headers, READ_ANY)
    core.require_package(package_id)
    rows = core.package_enrollments(package_id)
    return _page(request.args, rows, shapes.enrollment)