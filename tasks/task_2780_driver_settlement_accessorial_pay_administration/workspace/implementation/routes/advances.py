"""Advances, fuel cards and cancellation (PRD section 3.6)."""
from flask import Blueprint, request

import clock
import constants
import db
import listing
import middleware
import queries
import response
import serializers
import validators
from errors import ApiError

bp = Blueprint("advances", __name__)

ADMIN = constants.ROLE_PAYROLL_ADMIN
CLERK = constants.ROLE_SETTLEMENT_CLERK
APPROVER = constants.ROLE_SETTLEMENT_APPROVER
AUDITOR = constants.ROLE_COMPLIANCE_AUDITOR
DRIVER = constants.ROLE_DRIVER

ALL_READ = (ADMIN, CLERK, APPROVER, AUDITOR, DRIVER)


def find_advance(advance_id):
    advance = db.advances.get(advance_id)
    if advance is None:
        raise ApiError("ERR_ADVANCE_NOT_FOUND")
    return advance


@bp.route("/driver-pay/advances", methods=["POST"])
def issue_advance():
    middleware.authorize(ADMIN, CLERK)
    body = validators.body_of(request)
    validators.require(body, ["driver_id", "advance_type", "amount_cents"])
    driver_id = validators.id_value(body, "driver_id", required=True)
    advance_type = validators.enum_value(
        body, "advance_type", constants.ADVANCE_TYPES, required=True
    )
    amount_cents = validators.int_value(body, "amount_cents", required=True, minimum=1)
    installment_cents = validators.int_value(body, "installment_cents", minimum=1)
    if installment_cents is None:
        # Omitted means the whole principal is recoverable from one settlement.
        installment_cents = amount_cents

    driver = db.drivers.get(driver_id)
    if driver is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND")
    if driver["employment_status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_NOT_ACTIVE")

    exposure = amount_cents + queries.driver_advance_outstanding_cents(driver_id)
    if exposure > constants.ADVANCE_OUTSTANDING_LIMIT_CENTS:
        raise ApiError("ERR_ADVANCE_LIMIT_EXCEEDED")

    record = {
        "driver_id": driver_id,
        "advance_type": advance_type,
        "amount_cents": amount_cents,
        "installment_cents": installment_cents,
        "status": "ISSUED",
        "issued_at": clock.now(),
    }
    db.stamp_new(record)
    db.advances[record["id"]] = record
    return response.object_response(serializers.advance(record), 201)


@bp.route("/driver-pay/advances", methods=["GET"])
def list_advances():
    user_id, role = middleware.authorize(*ALL_READ)
    rows = db.ordered(db.advances)
    rows = listing.apply_filters(
        rows,
        request.args,
        [
            ("driver_id", "driver_id", None),
            ("status", "status", constants.ADVANCE_STATUSES),
            ("advance_type", "advance_type", constants.ADVANCE_TYPES),
        ],
    )
    rows = listing.narrow_to_driver(rows, role, user_id)
    return listing.page(rows, request.args, serializers.advance)


@bp.route("/driver-pay/advances/<advance_id>", methods=["GET"])
def read_advance(advance_id):
    user_id, role = middleware.authorize(*ALL_READ)
    advance = find_advance(advance_id)
    middleware.check_scope(user_id, role, advance["driver_id"])
    return response.object_response(serializers.advance(advance))


@bp.route("/driver-pay/advances/<advance_id>/cancel", methods=["POST"])
def cancel_advance(advance_id):
    middleware.authorize(ADMIN)
    advance = find_advance(advance_id)
    if advance["status"] != "ISSUED":
        raise ApiError("ERR_ADVANCE_NOT_CANCELLABLE")
    advance["status"] = "CANCELLED"
    db.touch(advance)
    return response.object_response(serializers.advance(advance))
