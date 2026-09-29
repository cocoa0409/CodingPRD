"""Dispute filing and the cyclic adjudication lifecycle (PRD section 3.9)."""
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
from services import dispute as dispute_service

bp = Blueprint("disputes", __name__)

ADMIN = constants.ROLE_PAYROLL_ADMIN
CLERK = constants.ROLE_SETTLEMENT_CLERK
APPROVER = constants.ROLE_SETTLEMENT_APPROVER
AUDITOR = constants.ROLE_COMPLIANCE_AUDITOR
DRIVER = constants.ROLE_DRIVER

ALL_READ = (ADMIN, CLERK, APPROVER, AUDITOR, DRIVER)


def find_dispute(dispute_id):
    record = db.disputes.get(dispute_id)
    if record is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND")
    return record


@bp.route("/driver-pay/disputes", methods=["POST"])
def file_dispute():
    user_id, role = middleware.authorize(DRIVER, ADMIN, CLERK)
    body = validators.body_of(request)
    if body.get("driver_id") is not None:
        middleware.check_scope(user_id, role, body.get("driver_id"))
    validators.require(body, ["dispute_kind", "driver_id", "narrative"])
    dispute_kind = validators.enum_value(
        body, "dispute_kind", constants.DISPUTE_KINDS, required=True
    )
    driver_id = validators.id_value(body, "driver_id", required=True)
    narrative = validators.string_value(body, "narrative", required=True)
    evidence_doc_ref = validators.string_value(body, "evidence_doc_ref")

    if dispute_kind == "MILEAGE":
        validators.require(body, ["load_id", "claimed_guide", "claimed_miles"])
        load_id = validators.id_value(body, "load_id", required=True)
        claimed_guide = validators.enum_value(
            body, "claimed_guide", constants.MILEAGE_GUIDES, required=True
        )
        claimed_miles = validators.int_value(body, "claimed_miles", required=True, minimum=1)
        validators.must_be_null(
            body, ["settlement_id", "claimed_amount_cents", "disputed_line_type"]
        )
        settlement_id = None
        claimed_amount_cents = None
        disputed_line_type = None
    else:
        validators.require(body, ["settlement_id", "claimed_amount_cents", "disputed_line_type"])
        settlement_id = validators.id_value(body, "settlement_id", required=True)
        claimed_amount_cents = validators.int_value(
            body, "claimed_amount_cents", required=True, minimum=1
        )
        disputed_line_type = validators.enum_value(
            body, "disputed_line_type", constants.DISPUTED_LINE_TYPES, required=True
        )
        validators.must_be_null(body, ["load_id", "claimed_guide", "claimed_miles"])
        load_id = None
        claimed_guide = None
        claimed_miles = None

    driver = db.drivers.get(driver_id)
    if driver is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND")
    load = None
    if load_id is not None:
        load = db.loads.get(load_id)
        if load is None:
            raise ApiError("ERR_LOAD_NOT_FOUND")
    origin = None
    if settlement_id is not None:
        origin = db.settlements.get(settlement_id)
        if origin is None:
            raise ApiError("ERR_SETTLEMENT_NOT_FOUND")

    if load is not None and load["movement_status"] != "DELIVERED":
        raise ApiError("ERR_LOAD_NOT_DELIVERED")

    probe = {
        "dispute_kind": dispute_kind,
        "driver_id": driver_id,
        "load_id": load_id,
        "settlement_id": settlement_id,
    }
    reference = dispute_service.reference_instant(probe)
    if reference is not None and clock.now() > clock.plus_days(
        reference, constants.DISPUTE_WINDOW_DAYS
    ):
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED")

    for other in db.disputes.values():
        if other["dispute_kind"] != dispute_kind:
            continue
        if other["status"] not in ("OPEN", "UNDER_REVIEW"):
            continue
        if load_id is not None and other["load_id"] == load_id:
            raise ApiError("ERR_DISPUTE_ALREADY_OPEN")
        if settlement_id is not None and other["settlement_id"] == settlement_id:
            raise ApiError("ERR_DISPUTE_ALREADY_OPEN")

    if load is not None:
        if (
            claimed_guide == load["applied_mileage_guide"]
            and claimed_miles == load["base_guide_miles"]
        ):
            raise ApiError("ERR_MILEAGE_CLAIM_UNCHANGED")
        if load["driver_id"] != driver_id:
            raise ApiError("ERR_DRIVER_MISMATCH")
    if origin is not None and origin["driver_id"] != driver_id:
        raise ApiError("ERR_DRIVER_MISMATCH")

    record = {
        "dispute_kind": dispute_kind,
        "driver_id": driver_id,
        "load_id": load_id,
        "settlement_id": settlement_id,
        "claimed_guide": claimed_guide,
        "claimed_miles": claimed_miles,
        "claimed_amount_cents": claimed_amount_cents,
        "disputed_line_type": disputed_line_type,
        "evidence_doc_ref": evidence_doc_ref,
        "narrative": narrative,
        "status": "OPEN",
        "reopen_count": 0,
        "resolution_note": None,
        "resolution_correction_id": None,
        "adjustment_cents": None,
        "submitted_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "resolved_by_user_id": None,
    }
    db.stamp_new(record)
    db.disputes[record["id"]] = record
    return response.object_response(serializers.dispute(record), 201)


@bp.route("/driver-pay/disputes", methods=["GET"])
def list_disputes():
    user_id, role = middleware.authorize(*ALL_READ)
    rows = db.ordered(db.disputes)
    rows = listing.apply_filters(
        rows,
        request.args,
        [
            ("driver_id", "driver_id", None),
            ("load_id", "load_id", None),
            ("settlement_id", "settlement_id", None),
            ("resolution_correction_id", "resolution_correction_id", None),
            ("status", "status", constants.DISPUTE_STATUSES),
            ("dispute_kind", "dispute_kind", constants.DISPUTE_KINDS),
        ],
    )
    rows = listing.narrow_to_driver(rows, role, user_id)
    return listing.page(rows, request.args, serializers.dispute)


@bp.route("/driver-pay/disputes/<dispute_id>", methods=["GET"])
def read_dispute(dispute_id):
    user_id, role = middleware.authorize(*ALL_READ)
    record = find_dispute(dispute_id)
    middleware.check_scope(user_id, role, record["driver_id"])
    return response.object_response(serializers.dispute(record))


@bp.route("/driver-pay/disputes/<dispute_id>/review", methods=["POST"])
def review(dispute_id):
    user_id, _role = middleware.authorize(ADMIN, CLERK)
    record = find_dispute(dispute_id)
    if record["status"] != "OPEN":
        raise ApiError("ERR_DISPUTE_STATE_INVALID")
    record["status"] = "UNDER_REVIEW"
    record["reviewed_by_user_id"] = user_id
    db.touch(record)
    return response.object_response(serializers.dispute(record))


@bp.route("/driver-pay/disputes/<dispute_id>/resolve", methods=["POST"])
def resolve(dispute_id):
    user_id, _role = middleware.authorize(APPROVER, ADMIN)
    body = validators.body_of(request)
    validators.require(body, ["outcome"])
    outcome = validators.enum_value(body, "outcome", constants.DISPUTE_OUTCOMES, required=True)
    resolution_note = validators.string_value(body, "resolution_note")
    # adjustment_cents is validated for shape but never trusted: the recorded
    # figure is always the signed delta the server derives itself.
    validators.int_value(body, "adjustment_cents")

    record = find_dispute(dispute_id)
    if record["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_DISPUTE_STATE_INVALID")
    if user_id == record["reviewed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if record["dispute_kind"] == "PAY":
        origin = db.settlements.get(record["settlement_id"])
        if origin is not None and user_id == origin["prepared_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if outcome == "DENY":
        dispute_service.deny(record, resolution_note, user_id)
    else:
        dispute_service.uphold(record, resolution_note, user_id)
    return response.object_response(serializers.dispute(record))


@bp.route("/driver-pay/disputes/<dispute_id>/reopen", methods=["POST"])
def reopen(dispute_id):
    user_id, role = middleware.authorize(DRIVER, ADMIN)
    body = validators.body_of(request)
    validators.require(body, ["narrative"])
    narrative = validators.string_value(body, "narrative", required=True)
    evidence_doc_ref = validators.string_value(body, "evidence_doc_ref")

    record = find_dispute(dispute_id)
    middleware.check_scope(user_id, role, record["driver_id"])
    if record["status"] != "DENIED":
        raise ApiError("ERR_DISPUTE_STATE_INVALID")
    if record["reopen_count"] >= constants.DISPUTE_REOPEN_LIMIT:
        raise ApiError("ERR_DISPUTE_REOPEN_LIMIT")

    record["status"] = "OPEN"
    record["reopen_count"] = record["reopen_count"] + 1
    record["narrative"] = narrative
    if evidence_doc_ref is not None:
        record["evidence_doc_ref"] = evidence_doc_ref
    record["resolution_note"] = None
    record["resolved_by_user_id"] = None
    record["reviewed_by_user_id"] = None
    db.touch(record)
    return response.object_response(serializers.dispute(record))


@bp.route("/driver-pay/disputes/<dispute_id>/withdraw", methods=["POST"])
def withdraw(dispute_id):
    user_id, role = middleware.authorize(DRIVER, ADMIN)
    record = find_dispute(dispute_id)
    middleware.check_scope(user_id, role, record["driver_id"])
    if record["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise ApiError("ERR_DISPUTE_STATE_INVALID")
    # Any reviewed_by_user_id already recorded is retained as history.
    record["status"] = "WITHDRAWN"
    db.touch(record)
    return response.object_response(serializers.dispute(record))
