"""Settlement statements: opening, sweeping, preparing, approving, paying,
voiding (PRD sections 3.7 and 3.8)."""
from flask import Blueprint, request

import constants
import db
import listing
import middleware
import queries
import response
import serializers
import validators
from errors import ApiError
from services import settlement as settlement_service

bp = Blueprint("settlements", __name__)

ADMIN = constants.ROLE_PAYROLL_ADMIN
CLERK = constants.ROLE_SETTLEMENT_CLERK
APPROVER = constants.ROLE_SETTLEMENT_APPROVER
AUDITOR = constants.ROLE_COMPLIANCE_AUDITOR
DRIVER = constants.ROLE_DRIVER

ALL_READ = (ADMIN, CLERK, APPROVER, AUDITOR, DRIVER)


def find_settlement(settlement_id):
    record = db.settlements.get(settlement_id)
    if record is None:
        raise ApiError("ERR_SETTLEMENT_NOT_FOUND")
    return record


def driver_of(settlement):
    driver = db.drivers.get(settlement["driver_id"])
    if driver is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND")
    return driver


@bp.route("/driver-pay/settlements", methods=["POST"])
def open_settlement():
    middleware.authorize(ADMIN, CLERK)
    body = validators.body_of(request)
    validators.require(body, ["driver_id", "period_start", "period_end"])
    driver_id = validators.id_value(body, "driver_id", required=True)
    period_start = validators.ts_value(body, "period_start", required=True)
    period_end = validators.ts_value(body, "period_end", required=True)

    driver = db.drivers.get(driver_id)
    if driver is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND")
    if driver["employment_status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_NOT_ACTIVE")
    if period_end <= period_start:
        raise ApiError("ERR_INTERVAL_INVALID")
    for other in queries.settlements_of(driver_id):
        if other["status"] == "VOIDED":
            continue
        if period_start < other["period_end"] and other["period_start"] < period_end:
            raise ApiError("ERR_SETTLEMENT_PERIOD_OVERLAP")

    record = {
        "driver_id": driver_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "prepared_by_user_id": None,
        "approved_by_user_id": None,
        "prepared_at": None,
        "approved_at": None,
        "paid_at": None,
        "voided_at": None,
        "payment_reference": None,
        "void_reason_code": None,
        "itemization_required": driver["driver_type"] == "LEASED_OPERATOR",
        "linehaul_total_cents": 0,
        "accessorial_total_cents": 0,
        "retro_correction_total_cents": 0,
        "gross_pay_cents": 0,
        "days_out_count": 0,
        "per_diem_non_taxable_cents": 0,
        "per_diem_excess_taxable_cents": 0,
        "taxable_wages_cents": 0,
        "escrow_deduction_cents": 0,
        "advance_recovery_cents": 0,
        "deduction_total_cents": 0,
        "net_pay_cents": 0,
    }
    db.stamp_new(record)
    db.settlements[record["id"]] = record
    return response.object_response(serializers.settlement(record), 201)


@bp.route("/driver-pay/settlements", methods=["GET"])
def list_settlements():
    user_id, role = middleware.authorize(*ALL_READ)
    rows = db.ordered(db.settlements)
    rows = listing.apply_filters(
        rows,
        request.args,
        [
            ("driver_id", "driver_id", None),
            ("status", "status", constants.SETTLEMENT_STATUSES),
        ],
    )
    rows = listing.narrow_to_driver(rows, role, user_id)
    return listing.page(rows, request.args, serializers.settlement)


@bp.route("/driver-pay/settlements/<settlement_id>", methods=["GET"])
def read_settlement(settlement_id):
    user_id, role = middleware.authorize(*ALL_READ)
    record = find_settlement(settlement_id)
    middleware.check_scope(user_id, role, record["driver_id"])
    return response.object_response(serializers.settlement(record))


@bp.route("/driver-pay/settlements/<settlement_id>/lines", methods=["GET"])
def list_lines(settlement_id):
    user_id, role = middleware.authorize(*ALL_READ)
    record = find_settlement(settlement_id)
    middleware.check_scope(user_id, role, record["driver_id"])
    rows = queries.lines_of(settlement_id)
    rows = listing.apply_filters(
        rows, request.args, [("line_type", "line_type", constants.LINE_TYPES)]
    )
    return listing.page(rows, request.args, serializers.settlement_line)


@bp.route("/driver-pay/settlements/<settlement_id>/apply-corrections", methods=["POST"])
def apply_corrections(settlement_id):
    middleware.authorize(ADMIN, CLERK)
    body = validators.body_of(request)
    validators.require(body, ["expected_settlement_version"])
    expected = validators.int_value(body, "expected_settlement_version", required=True)

    record = find_settlement(settlement_id)
    if expected != record["version"]:
        raise ApiError("ERR_STALE_SETTLEMENT_VERSION")
    if record["status"] != "DRAFT":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID")
    driver = driver_of(record)
    settlement_service.apply_corrections(record, driver)
    return response.object_response(serializers.settlement(record))


@bp.route("/driver-pay/settlements/<settlement_id>/prepare", methods=["POST"])
def prepare(settlement_id):
    user_id, _role = middleware.authorize(ADMIN, CLERK)
    record = find_settlement(settlement_id)
    driver = driver_of(record)

    if driver["employment_status"] not in ("ACTIVE", "SUSPENDED", "TERMINATED"):
        raise ApiError("ERR_DRIVER_NOT_ACTIVE")
    if record["status"] != "DRAFT":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID")
    if queries.settlement_hold(driver["id"]):
        raise ApiError("ERR_SETTLEMENT_HOLD_ACTIVE")

    settlement_service.prepare(record, driver, user_id)
    return response.object_response(serializers.settlement(record))


@bp.route("/driver-pay/settlements/<settlement_id>/approve", methods=["POST"])
def approve(settlement_id):
    user_id, _role = middleware.authorize(APPROVER, ADMIN)
    record = find_settlement(settlement_id)
    if record["status"] != "PREPARED":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID")
    if user_id == record["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    driver = driver_of(record)
    if queries.settlement_hold(driver["id"]):
        raise ApiError("ERR_SETTLEMENT_HOLD_ACTIVE")
    settlement_service.approve(record, driver, user_id)
    return response.object_response(serializers.settlement(record))


@bp.route("/driver-pay/settlements/<settlement_id>/pay", methods=["POST"])
def pay(settlement_id):
    user_id, _role = middleware.authorize(ADMIN)
    body = validators.body_of(request)
    validators.require(body, ["payment_reference"])
    payment_reference = validators.string_value(body, "payment_reference", required=True)

    record = find_settlement(settlement_id)
    if record["status"] != "APPROVED":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID")
    if user_id == record["approved_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    settlement_service.pay(record, payment_reference)
    return response.object_response(serializers.settlement(record))


@bp.route("/driver-pay/settlements/<settlement_id>/void", methods=["POST"])
def void(settlement_id):
    user_id, _role = middleware.authorize(ADMIN)
    body = validators.body_of(request)
    validators.require(body, ["void_reason_code"])
    reason = validators.enum_value(
        body, "void_reason_code", constants.VOID_REASON_CODES, required=True
    )

    record = find_settlement(settlement_id)
    if record["status"] in ("PAID", "VOIDED"):
        raise ApiError("ERR_SETTLEMENT_TERMINAL")
    driver = driver_of(record)
    settlement_service.void(record, driver, reason, user_id)
    return response.object_response(serializers.settlement(record))
