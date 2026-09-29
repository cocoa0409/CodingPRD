"""Receipts, scanned unit lines, return-line reads and fraud checks."""

from flask import Blueprint

import aggregates
import calc
import constants as K
import db
import middleware as mw
import query
import refs
import response
import serialize
import services
import shapes
from errors import ApiError

bp = Blueprint("receipts", __name__)

ALL_ROLES = (
    "CenterAdmin",
    "ReceivingClerk",
    "GradingInspector",
    "RefurbTechnician",
    "DispositionSupervisor",
    "RefundAnalyst",
    "ClientRep",
)
FRAUD_ROLES = (
    "CenterAdmin",
    "ReceivingClerk",
    "GradingInspector",
    "DispositionSupervisor",
    "RefundAnalyst",
)


@bp.post("/receipts")
def create_receipt():
    user_id, _role = mw.require("ReceivingClerk", "CenterAdmin")
    body = response.body_json()
    rma_id = shapes.req_id(body, "rma_id")
    tracking_reference = shapes.req_str(body, "tracking_reference")
    gross_weight_grams = shapes.req_int(body, "gross_weight_grams", 0)
    rma = services.must_rma(rma_id)
    client = services.must_client(rma["client_id"])
    services.require_active(client)
    # §3.2: "Once an authorization is EXPIRED, any attempt to receive against it
    # or reissue it fails with ERR_RMA_EXPIRED" — the expiry answer outranks the
    # generic state answer on this endpoint.
    if rma["status"] != "EXPIRED" and rma["status"] not in (
        "ISSUED",
        "PARTIALLY_RECEIVED",
    ):
        raise ApiError("ERR_RMA_INVALID_STATE")
    if rma["status"] == "EXPIRED":
        raise ApiError("ERR_RMA_EXPIRED")
    expires_at = db.parse_instant(rma["expires_at"])
    if expires_at is not None and expires_at <= db.now():
        raise ApiError("ERR_RMA_EXPIRED")
    for existing in refs.receipts_of(rma):
        if existing["tracking_reference"] == tracking_reference:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field 'tracking_reference' must be unique for the authorization.",
            )
    expected = calc.expected_weight_grams(
        refs.rma_lines_of(rma), lambda key: db.get("catalog_items", key)
    )
    row = {
        "id": db.new_id(),
        "rma_id": rma["id"],
        "tracking_reference": tracking_reference,
        "gross_weight_grams": gross_weight_grams,
        "expected_weight_grams": expected,
        "empty_box_suspected": calc.empty_box_suspected(gross_weight_grams, expected),
        "received_at": db.now_str(),
        "scanned_by_user_id": user_id,
    }
    db.stamp_new(row)
    db.insert("receipts", row)
    return response.created(serialize.receipt(row))


@bp.get("/receipts/<receipt_id>")
def get_receipt(receipt_id):
    user_id, role = mw.require(
        "CenterAdmin", "ReceivingClerk", "GradingInspector", "RefundAnalyst", "ClientRep"
    )
    receipt = db.get("receipts", receipt_id)
    if receipt is not None:
        mw.scope(role, user_id, refs.client_id_of_receipt(receipt))
    receipt = services.must_receipt(receipt_id)
    return response.ok(serialize.receipt(receipt))


@bp.get("/receipts")
def list_receipts():
    user_id, role = mw.require(
        "CenterAdmin", "ReceivingClerk", "GradingInspector", "RefundAnalyst", "ClientRep"
    )
    rma_id = query.arg("rma_id")
    if rma_id is not None:
        services.must_rma(rma_id)
    rows = db.sorted_rows(db.all_rows("receipts"))
    if role == mw.CLIENT_REP:
        rows = [r for r in rows if refs.client_id_of_receipt(r) == user_id]
    rows = query.eq(rows, "rma_id", rma_id)
    rows = query.eq(rows, "empty_box_suspected", query.arg_bool("empty_box_suspected"))
    return response.paginate(rows, serialize.receipt)


@bp.post("/receipts/<receipt_id>/lines")
def scan_line(receipt_id):
    _user_id, _role = mw.require("ReceivingClerk", "CenterAdmin")
    body = response.body_json()
    rma_line_id = shapes.req_id(body, "rma_line_id")
    quantity = shapes.req_int(body, "quantity", 1, 999)
    reason_code = shapes.req_enum(body, "reason_code", K.REASON_CODES)
    scanned_serial = shapes.opt_str(body, "scanned_serial")
    rma_line = services.must_rma_line(rma_line_id)
    receipt = services.must_receipt(receipt_id)
    if rma_line["rma_id"] != receipt["rma_id"]:
        raise ApiError("ERR_LINE_RMA_MISMATCH")
    rma = services.must_rma(receipt["rma_id"])
    client = services.must_client(rma["client_id"])
    services.require_active(client)
    item = refs.item_of_rma_line(rma_line)
    if item is None:
        raise ApiError("ERR_CATALOG_ITEM_NOT_FOUND")
    if item["serialized"] and not scanned_serial:
        raise ApiError("ERR_SERIAL_REQUIRED")
    already = aggregates.rma_line_received_quantity(rma_line["id"])
    if already + quantity > rma_line["authorized_quantity"]:
        raise ApiError("ERR_AUTHORIZED_QUANTITY_EXCEEDED")

    received_at = db.parse_instant(receipt["received_at"])
    order_placed_at = db.parse_instant(rma["order_placed_at"])
    row = {
        "id": db.new_id(),
        "receipt_id": receipt["id"],
        "rma_line_id": rma_line["id"],
        "bay_id": None,
        "quantity": quantity,
        "scanned_serial": scanned_serial,
        "reason_code": reason_code,
        "condition_grade": "UNGRADED",
        "disposition": "PENDING",
        "disposition_state": "RECEIVED_UNGRADED",
        "financial_state": "HOLD_PENDING_DISPOSITION",
        "quarantine_start_at": None,
        "quarantine_end_at": None,
        "days_since_order": calc.days_since_order(order_placed_at, received_at),
        "recovery_value_cents": 0,
        "fraud_score_receipt": 0,
        "fraud_score_release": 0,
        "graded_by_user_id": None,
        "released_by_user_id": None,
    }
    db.stamp_new(row)
    db.insert("return_lines", row)
    services.run_receipt_fraud_checks(row, receipt, rma_line, item)
    aggregates.rederive_rma_status(rma)
    db.touch(rma)
    return response.created(serialize.return_line(row))


@bp.get("/return-lines/<return_line_id>")
def get_return_line(return_line_id):
    user_id, role = mw.require(*ALL_ROLES)
    line = db.get("return_lines", return_line_id)
    if line is not None:
        mw.scope(role, user_id, refs.client_id_of_return_line(line))
    line = services.must_return_line(return_line_id)
    return response.ok(serialize.return_line(line))


@bp.get("/return-lines")
def list_return_lines():
    user_id, role = mw.require(*ALL_ROLES)
    bay_id = query.arg("bay_id")
    if bay_id is not None:
        services.must_bay(bay_id)
    rma_line_id = query.arg("rma_line_id")
    if rma_line_id is not None:
        services.must_rma_line(rma_line_id)
    receipt_id = query.arg("receipt_id")
    if receipt_id is not None:
        services.must_receipt(receipt_id)
    rows = db.sorted_rows(db.all_rows("return_lines"))
    if role == mw.CLIENT_REP:
        rows = [r for r in rows if refs.client_id_of_return_line(r) == user_id]
    rows = query.eq(rows, "receipt_id", receipt_id)
    rows = query.eq(rows, "rma_line_id", rma_line_id)
    rows = query.eq(rows, "bay_id", bay_id)
    rows = query.eq(rows, "disposition", query.arg("disposition"))
    rows = query.eq(rows, "disposition_state", query.arg("disposition_state"))
    rows = query.eq(rows, "financial_state", query.arg("financial_state"))
    rows = query.eq(rows, "condition_grade", query.arg("condition_grade"))
    return response.paginate(rows, serialize.return_line)


@bp.get("/return-lines/<return_line_id>/fraud-checks")
def list_line_fraud_checks(return_line_id):
    mw.require(*FRAUD_ROLES)
    services.must_return_line(return_line_id)
    rows = refs.fraud_checks_of_line(return_line_id)
    rows = query.eq(rows, "check_type", query.arg("check_type"))
    rows = query.eq(rows, "evaluated_stage", query.arg("evaluated_stage"))
    return response.paginate(rows, serialize.fraud_check)


@bp.get("/fraud-checks/<fraud_check_id>")
def get_fraud_check(fraud_check_id):
    mw.require(*FRAUD_ROLES)
    check = services.must_fraud_check(fraud_check_id)
    return response.ok(serialize.fraud_check(check))


@bp.get("/fraud-checks")
def list_fraud_checks():
    mw.require(*FRAUD_ROLES)
    rows = db.sorted_rows(db.all_rows("fraud_checks"))
    rows = query.eq(rows, "return_line_id", query.arg("return_line_id"))
    rows = query.eq(rows, "check_type", query.arg("check_type"))
    rows = query.eq(rows, "evaluated_stage", query.arg("evaluated_stage"))
    rows = query.eq(rows, "outcome", query.arg("outcome"))
    return response.paginate(rows, serialize.fraud_check)
