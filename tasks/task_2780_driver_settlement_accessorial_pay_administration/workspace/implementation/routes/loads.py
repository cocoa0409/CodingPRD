"""Load tender, dispatch and delivery (PRD section 3.4)."""
from flask import Blueprint, request

import clock
import constants
import db
import listing
import middleware
import response
import serializers
import validators
from errors import ApiError
from services import load_pay

bp = Blueprint("loads", __name__)

ADMIN = constants.ROLE_PAYROLL_ADMIN
CLERK = constants.ROLE_SETTLEMENT_CLERK
APPROVER = constants.ROLE_SETTLEMENT_APPROVER
AUDITOR = constants.ROLE_COMPLIANCE_AUDITOR
DRIVER = constants.ROLE_DRIVER

ALL_READ = (ADMIN, CLERK, APPROVER, AUDITOR, DRIVER)


def find_load(load_id):
    load = db.loads.get(load_id)
    if load is None:
        raise ApiError("ERR_LOAD_NOT_FOUND")
    return load


@bp.route("/driver-pay/loads", methods=["POST"])
def tender_load():
    middleware.authorize(ADMIN, CLERK)
    body = validators.body_of(request)
    validators.require(body, ["driver_id", "linehaul_revenue_cents", "practical_miles", "hhg_miles"])
    driver_id = validators.id_value(body, "driver_id", required=True)
    record = {
        "driver_id": driver_id,
        "settlement_id": None,
        "pay_package_id_snapshot": None,
        "origin_zip": validators.string_value(body, "origin_zip"),
        "dest_zip": validators.string_value(body, "dest_zip"),
        "linehaul_revenue_cents": validators.int_value(body, "linehaul_revenue_cents", required=True, minimum=1),
        "practical_miles": validators.int_value(body, "practical_miles", required=True, minimum=1),
        "hhg_miles": validators.int_value(body, "hhg_miles", required=True, minimum=1),
        "stop_count": validators.int_value(body, "stop_count", default=1, minimum=1),
        "hours_worked_minutes": validators.int_value(body, "hours_worked_minutes", default=0, minimum=0),
        "tarp_required": validators.bool_value(body, "tarp_required", default=False),
        "dispatched_at": None,
        "delivered_at": None,
        "movement_status": "TENDERED",
        "pay_status": "UNPAID",
        "applied_mileage_guide": None,
        "base_guide_miles": None,
        "paid_miles": None,
        "short_haul_floor_applied": False,
        "linehaul_pay_cents": None,
        "linehaul_line_type": None,
    }

    driver = db.drivers.get(driver_id)
    if driver is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND")
    if driver["employment_status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_NOT_ACTIVE")

    db.stamp_new(record)
    db.loads[record["id"]] = record
    return response.object_response(serializers.load(record), 201)


@bp.route("/driver-pay/loads", methods=["GET"])
def list_loads():
    user_id, role = middleware.authorize(*ALL_READ)
    rows = db.ordered(db.loads)
    rows = listing.apply_filters(
        rows,
        request.args,
        [
            ("driver_id", "driver_id", None),
            ("settlement_id", "settlement_id", None),
            ("pay_package_id_snapshot", "pay_package_id_snapshot", None),
            ("movement_status", "movement_status", constants.MOVEMENT_STATUSES),
            ("pay_status", "pay_status", constants.PAY_STATUSES),
        ],
    )
    rows = listing.narrow_to_driver(rows, role, user_id)
    return listing.page(rows, request.args, serializers.load)


@bp.route("/driver-pay/loads/<load_id>", methods=["GET"])
def read_load(load_id):
    user_id, role = middleware.authorize(*ALL_READ)
    load = find_load(load_id)
    middleware.check_scope(user_id, role, load["driver_id"])
    return response.object_response(serializers.load(load))


@bp.route("/driver-pay/loads/<load_id>/dispatch", methods=["POST"])
def dispatch_load(load_id):
    middleware.authorize(ADMIN, CLERK)
    body = validators.body_of(request)
    dispatched_at = validators.ts_value(body, "dispatched_at")

    load = find_load(load_id)
    if load["movement_status"] != "TENDERED":
        raise ApiError("ERR_LOAD_NOT_DELIVERED")
    driver = db.drivers.get(load["driver_id"])
    package = db.pay_packages.get(driver["pay_package_id"]) if driver and driver["pay_package_id"] else None
    if package is None or package["status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_HAS_NO_PAY_PACKAGE")

    load["movement_status"] = "IN_TRANSIT"
    load["dispatched_at"] = dispatched_at if dispatched_at is not None else clock.now()
    # The snapshot pins the package, so a later revision cannot re-rate this load.
    load["pay_package_id_snapshot"] = package["id"]
    db.touch(load)
    return response.object_response(serializers.load(load))


@bp.route("/driver-pay/loads/<load_id>/deliver", methods=["POST"])
def deliver_load(load_id):
    middleware.authorize(ADMIN, CLERK)
    body = validators.body_of(request)
    delivered_at = validators.ts_value(body, "delivered_at")
    hours_worked_minutes = validators.int_value(body, "hours_worked_minutes", minimum=0)
    stop_count = validators.int_value(body, "stop_count", minimum=1)

    load = find_load(load_id)
    if load["movement_status"] != "IN_TRANSIT":
        raise ApiError("ERR_LOAD_NOT_DELIVERED")
    effective = delivered_at if delivered_at is not None else clock.now()
    if load["dispatched_at"] is not None and effective < load["dispatched_at"]:
        raise ApiError("ERR_INVALID_FIELD_VALUE", "delivered_at must be at or after dispatched_at.")

    if hours_worked_minutes is not None:
        load["hours_worked_minutes"] = hours_worked_minutes
    if stop_count is not None:
        load["stop_count"] = stop_count
    load["movement_status"] = "DELIVERED"
    load["delivered_at"] = effective
    load["pay_status"] = "ACCRUED"
    load_pay.recompute_from_snapshot(load)
    db.touch(load)
    return response.object_response(serializers.load(load))
