"""Retroactive corrections: reading and cancellation (PRD section 3.9)."""
from flask import Blueprint, request

import constants
import db
import listing
import middleware
import response
import serializers
from errors import ApiError
from services import dispute as dispute_service

bp = Blueprint("retro", __name__)

ADMIN = constants.ROLE_PAYROLL_ADMIN
CLERK = constants.ROLE_SETTLEMENT_CLERK
APPROVER = constants.ROLE_SETTLEMENT_APPROVER
AUDITOR = constants.ROLE_COMPLIANCE_AUDITOR
DRIVER = constants.ROLE_DRIVER

ALL_READ = (ADMIN, CLERK, APPROVER, AUDITOR, DRIVER)


def find_correction(correction_id):
    record = db.retro_corrections.get(correction_id)
    if record is None:
        raise ApiError("ERR_RETRO_CORRECTION_NOT_FOUND")
    return record


@bp.route("/driver-pay/retro-corrections", methods=["GET"])
def list_corrections():
    user_id, role = middleware.authorize(*ALL_READ)
    rows = db.ordered(db.retro_corrections)
    rows = listing.apply_filters(
        rows,
        request.args,
        [
            ("driver_id", "driver_id", None),
            ("origin_settlement_id", "origin_settlement_id", None),
            ("applied_settlement_id", "applied_settlement_id", None),
            ("source_load_id", "source_load_id", None),
            ("source_dispute_id", "source_dispute_id", None),
            ("status", "status", constants.CORRECTION_STATUSES),
        ],
    )
    rows = listing.narrow_to_driver(rows, role, user_id)
    return listing.page(rows, request.args, serializers.retro_correction)


@bp.route("/driver-pay/retro-corrections/<correction_id>", methods=["GET"])
def read_correction(correction_id):
    user_id, role = middleware.authorize(*ALL_READ)
    record = find_correction(correction_id)
    middleware.check_scope(user_id, role, record["driver_id"])
    return response.object_response(serializers.retro_correction(record))


@bp.route("/driver-pay/retro-corrections/<correction_id>/cancel", methods=["POST"])
def cancel_correction(correction_id):
    user_id, _role = middleware.authorize(ADMIN)
    record = find_correction(correction_id)
    if record["status"] != "PENDING" or record["applied_settlement_id"] is not None:
        raise ApiError("ERR_CORRECTION_NOT_PENDING")
    dispute_service.cancel_correction(record, user_id)
    return response.object_response(serializers.retro_correction(record))
