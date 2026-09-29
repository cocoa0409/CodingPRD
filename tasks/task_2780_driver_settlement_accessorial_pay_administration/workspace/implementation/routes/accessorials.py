"""Accessorial claim submission, documentation and adjudication (PRD section 3.5)."""
from flask import Blueprint, request

import constants
import db
import listing
import middleware
import response
import serializers
import validators
from errors import ApiError
from services import accessorial as accessorial_service

bp = Blueprint("accessorials", __name__)

ADMIN = constants.ROLE_PAYROLL_ADMIN
CLERK = constants.ROLE_SETTLEMENT_CLERK
APPROVER = constants.ROLE_SETTLEMENT_APPROVER
AUDITOR = constants.ROLE_COMPLIANCE_AUDITOR
DRIVER = constants.ROLE_DRIVER

ALL_READ = (ADMIN, CLERK, APPROVER, AUDITOR, DRIVER)


def find_claim(claim_id):
    claim = db.accessorial_claims.get(claim_id)
    if claim is None:
        raise ApiError("ERR_ACCESSORIAL_CLAIM_NOT_FOUND")
    return claim


def _already_settled(claim):
    if claim["status"] == "PAID" or claim["settlement_id"] is not None:
        raise ApiError("ERR_CLAIM_ALREADY_SETTLED")


@bp.route("/driver-pay/accessorial-claims", methods=["POST"])
def submit_claim():
    user_id, role = middleware.authorize(ADMIN, CLERK, DRIVER)
    body = validators.body_of(request)
    if body.get("driver_id") is not None:
        middleware.check_scope(user_id, role, body.get("driver_id"))
    validators.require(body, ["load_id", "driver_id", "accessorial_type", "start_at", "end_at"])
    load_id = validators.id_value(body, "load_id", required=True)
    driver_id = validators.id_value(body, "driver_id", required=True)
    accessorial_type = validators.enum_value(
        body, "accessorial_type", constants.ACCESSORIAL_TYPES, required=True
    )
    start_at = validators.ts_value(body, "start_at", required=True)
    end_at = validators.ts_value(body, "end_at", required=True)
    document_ref = validators.string_value(body, "document_ref")

    driver = db.drivers.get(driver_id)
    if driver is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND")
    load = db.loads.get(load_id)
    if load is None:
        raise ApiError("ERR_LOAD_NOT_FOUND")
    if driver["employment_status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_NOT_ACTIVE")
    if end_at <= start_at:
        raise ApiError("ERR_INTERVAL_INVALID")
    accessorial_service.check_overlap(load_id, driver_id, accessorial_type, start_at, end_at)
    if load["driver_id"] != driver_id:
        raise ApiError("ERR_DRIVER_MISMATCH")

    record = {
        "load_id": load_id,
        "driver_id": driver_id,
        "settlement_id": None,
        "accessorial_type": accessorial_type,
        "start_at": start_at,
        "end_at": end_at,
        "document_ref": document_ref,
        "documentation_required": accessorial_type in constants.DOCUMENTATION_REQUIRED_TYPES,
        "billable_units": 0,
        "amount_cents": 0,
        "status": "SUBMITTED",
        "reject_reason_code": None,
        "submitted_by_user_id": user_id,
        "approved_by_user_id": None,
    }
    db.stamp_new(record)
    db.accessorial_claims[record["id"]] = record
    return response.object_response(serializers.accessorial_claim(record), 201)


@bp.route("/driver-pay/accessorial-claims", methods=["GET"])
def list_claims():
    user_id, role = middleware.authorize(*ALL_READ)
    rows = db.ordered(db.accessorial_claims)
    rows = listing.apply_filters(
        rows,
        request.args,
        [
            ("driver_id", "driver_id", None),
            ("load_id", "load_id", None),
            ("settlement_id", "settlement_id", None),
            ("status", "status", constants.CLAIM_STATUSES),
            ("accessorial_type", "accessorial_type", constants.ACCESSORIAL_TYPES),
        ],
    )
    rows = listing.narrow_to_driver(rows, role, user_id)
    return listing.page(rows, request.args, serializers.accessorial_claim)


@bp.route("/driver-pay/accessorial-claims/<claim_id>", methods=["GET"])
def read_claim(claim_id):
    user_id, role = middleware.authorize(*ALL_READ)
    claim = find_claim(claim_id)
    middleware.check_scope(user_id, role, claim["driver_id"])
    return response.object_response(serializers.accessorial_claim(claim))


@bp.route("/driver-pay/accessorial-claims/<claim_id>/documents", methods=["POST"])
def attach_document(claim_id):
    user_id, role = middleware.authorize(ADMIN, CLERK, DRIVER)
    body = validators.body_of(request)
    validators.require(body, ["document_ref"])
    document_ref = validators.string_value(body, "document_ref", required=True)

    claim = find_claim(claim_id)
    middleware.check_scope(user_id, role, claim["driver_id"])
    _already_settled(claim)
    if claim["status"] not in ("SUBMITTED", "REJECTED"):
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED")

    claim["document_ref"] = document_ref
    if claim["status"] == "REJECTED":
        # A rejection for missing paperwork is not the end of the road.
        claim["status"] = "SUBMITTED"
    db.touch(claim)
    return response.object_response(serializers.accessorial_claim(claim))


@bp.route("/driver-pay/accessorial-claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    user_id, _role = middleware.authorize(ADMIN, CLERK)
    claim = find_claim(claim_id)
    load = db.loads.get(claim["load_id"])

    if load is None or load["movement_status"] != "DELIVERED":
        raise ApiError("ERR_LOAD_NOT_DELIVERED")
    _already_settled(claim)
    if claim["documentation_required"] and not claim["document_ref"]:
        raise ApiError("ERR_DOCUMENTATION_MISSING")

    if claim["accessorial_type"] == "TARPING" and not load["tarp_required"]:
        # Tarping pay for freight that needed no tarp is not payable.
        raise ApiError("ERR_ZERO_VALUE_ACCESSORIAL")
    billable_units, amount_cents = accessorial_service.price(claim, load)
    if amount_cents <= 0:
        raise ApiError("ERR_ZERO_VALUE_ACCESSORIAL")

    if load["pay_status"] in ("SETTLED", "ADJUSTED") or load["settlement_id"] is not None:
        raise ApiError("ERR_LOAD_ALREADY_SETTLED")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED")

    claim["billable_units"] = billable_units
    claim["amount_cents"] = amount_cents
    claim["status"] = "APPROVED"
    claim["approved_by_user_id"] = user_id
    db.touch(claim)
    return response.object_response(serializers.accessorial_claim(claim))


@bp.route("/driver-pay/accessorial-claims/<claim_id>/reject", methods=["POST"])
def reject_claim(claim_id):
    middleware.authorize(ADMIN, CLERK)
    body = validators.body_of(request)
    validators.require(body, ["reject_reason_code"])
    reason = validators.enum_value(
        body, "reject_reason_code", constants.REJECT_REASON_CODES, required=True
    )

    claim = find_claim(claim_id)
    _already_settled(claim)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED")

    claim["status"] = "REJECTED"
    claim["reject_reason_code"] = reason
    claim["amount_cents"] = 0
    db.touch(claim)
    return response.object_response(serializers.accessorial_claim(claim))
