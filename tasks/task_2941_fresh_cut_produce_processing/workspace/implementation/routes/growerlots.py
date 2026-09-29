"""Grower lots, their adjudication and recall, plus raw receipts and disposition."""

from decimal import Decimal

from flask import Blueprint

import db
import enums
import serializers
from envelope import (
    actor,
    enum_param,
    listing,
    object_response,
    raw_body,
    read_body,
    require,
    str_param,
)
from errors import ApiError
from flask import g
from services import cascades, lots
from util import now_dt, q2

bp = Blueprint("growerlots", __name__)

MAX_RECEIVING_TEMP_C = Decimal("4.4")
WARN_RECEIVING_TEMP_C = Decimal("3.3")
TEMP_DEDUCTION_DAYS = {"IN_SPEC": 0, "MARGINAL": 1, "OUT_OF_SPEC": 2}

CREATE_LOT = (
    ("grower_code", "str", True),
    ("ranch_block", "str", True),
    ("commodity_class", "enum", True, {"values": enums.COMMODITY_CLASS}),
    ("harvest_datetime", "datetime", True),
    ("water_source", "enum", True, {"values": enums.WATER_SOURCE}),
    ("adjacent_animal_operation", "bool", False, {"default": False}),
    (
        "preharvest_test_result",
        "enum",
        True,
        {"values": enums.PREHARVEST_TEST_RESULT},
    ),
    ("prior_rejected_receipt_count", "int", False, {"ge": 0, "default": 0}),
)

CREATE_RECEIPT = (
    ("grower_lot_id", "id", True),
    ("received_at", "datetime", True),
    ("pulp_temp_c", "num", True),
    ("gross_weight_lb", "num", True, {"gt": Decimal(0)}),
    ("tare_weight_lb", "num", True, {"ge": Decimal(0)}),
)

DISPOSITION = (
    ("decision", "enum", True, {"values": enums.DISPOSITION_DECISION}),
    ("trim_loss_lb", "num", False),
    ("override_justification", "str", False),
)


def temp_grade_for(pulp_temp_c):
    if pulp_temp_c > MAX_RECEIVING_TEMP_C:
        return "OUT_OF_SPEC"
    if pulp_temp_c > WARN_RECEIVING_TEMP_C:
        return "MARGINAL"
    return "IN_SPEC"


@bp.post("/grower-lots")
@require("QATechnician")
def create_lot():
    body = read_body(CREATE_LOT)
    row = db.new_row(
        "grower_lots",
        {
            "grower_code": body["grower_code"],
            "ranch_block": body["ranch_block"],
            "commodity_class": body["commodity_class"],
            "water_source": body["water_source"],
            "adjacent_animal_operation": body["adjacent_animal_operation"],
            "preharvest_test_result": body["preharvest_test_result"],
            "prior_rejected_receipt_count": body["prior_rejected_receipt_count"],
            "status": "PENDING_APPROVAL",
            "preharvest_risk_score": None,
            "trailing_risk_score": None,
            "out_of_spec_receipt_count": 0,
            "env_positive_run_count": 0,
            "recalled_at": None,
            "_dt_recalled_at": None,
        },
    )
    db.set_instant(row, "harvest_datetime", body["harvest_datetime"])
    return object_response(serializers.grower_lot(row), 201)


@bp.get("/grower-lots")
@require("PlantAdmin", "QAManager", "QATechnician", "ReceivingClerk")
def list_lots():
    status = enum_param("status", enums.GROWER_LOT_STATUS)
    grower_code = str_param("grower_code")
    rows = db.rows("grower_lots")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if grower_code is not None:
        rows = [r for r in rows if r["grower_code"] == grower_code]
    return listing(rows, serializers.grower_lot)


@bp.get("/grower-lots/<lot_id>")
@require("PlantAdmin", "QAManager", "QATechnician", "ReceivingClerk")
def get_lot(lot_id):
    return object_response(serializers.grower_lot(db.get_or_404("grower_lots", lot_id)))


@bp.post("/grower-lots/<lot_id>/approve")
@require("QAManager")
def approve_lot(lot_id):
    lot = db.get_or_404("grower_lots", lot_id)
    if lot["status"] != "PENDING_APPROVAL":
        raise ApiError(
            "ERR_GROWER_LOT_INVALID_STATE", "only a PENDING_APPROVAL lot may be approved"
        )
    if lot["preharvest_test_result"] == "POSITIVE":
        lot["status"] = "REJECTED"
        lot["preharvest_risk_score"] = 0
        lot["trailing_risk_score"] = 0
    else:
        score = lots.preharvest_score(lot)
        lot["preharvest_risk_score"] = score
        lot["trailing_risk_score"] = score
        if score >= lots.RISK_SUSPEND_THRESHOLD:
            lot["status"] = "APPROVED"
        else:
            lot["status"] = "SUSPENDED"
        lots.refresh_counters(lot)
    db.touch(lot)
    return object_response(serializers.grower_lot(lot))


@bp.post("/grower-lots/<lot_id>/recall")
@require("QAManager")
def recall_lot(lot_id):
    lot = db.get_or_404("grower_lots", lot_id)
    if lot["status"] not in ("APPROVED", "SUSPENDED"):
        raise ApiError(
            "ERR_GROWER_LOT_INVALID_STATE",
            "only an APPROVED or SUSPENDED lot may be recalled",
        )
    cascades.recall(lot, now_dt())
    return object_response(serializers.grower_lot(lot))


@bp.post("/raw-receipts")
@require("ReceivingClerk")
def create_receipt():
    body = read_body(CREATE_RECEIPT)
    if body["tare_weight_lb"] >= body["gross_weight_lb"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "field 'tare_weight_lb' must be strictly less than gross_weight_lb",
        )
    db.get_or_404("grower_lots", body["grower_lot_id"])
    net = q2(body["gross_weight_lb"] - body["tare_weight_lb"])
    grade = temp_grade_for(body["pulp_temp_c"])
    row = db.new_row(
        "raw_receipts",
        {
            "grower_lot_id": body["grower_lot_id"],
            "pulp_temp_c": body["pulp_temp_c"],
            "gross_weight_lb": body["gross_weight_lb"],
            "tare_weight_lb": body["tare_weight_lb"],
            "net_weight_lb": net,
            "trim_loss_lb": None,
            "accepted_lb": None,
            "remaining_lb": None,
            "temp_grade": grade,
            "shelf_life_deduction_days": TEMP_DEDUCTION_DAYS[grade],
            "status": "PENDING_INSPECTION",
            "override_justification": None,
            "dispositioned_by_user_id": None,
        },
    )
    db.set_instant(row, "received_at", body["received_at"])
    return object_response(serializers.raw_receipt(row), 201)


@bp.get("/raw-receipts/<receipt_id>")
@require(
    "PlantAdmin", "QAManager", "QATechnician", "ReceivingClerk", "LineOperator"
)
def get_receipt(receipt_id):
    return object_response(
        serializers.raw_receipt(db.get_or_404("raw_receipts", receipt_id))
    )


@bp.get("/grower-lots/<lot_id>/raw-receipts")
@require(
    "PlantAdmin", "QAManager", "QATechnician", "ReceivingClerk", "LineOperator"
)
def list_lot_receipts(lot_id):
    status = enum_param("status", enums.RECEIPT_STATUS)
    grade = enum_param("temp_grade", enums.TEMP_GRADE)
    db.get_or_404("grower_lots", lot_id)
    rows = [r for r in db.rows("raw_receipts") if r["grower_lot_id"] == lot_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if grade is not None:
        rows = [r for r in rows if r["temp_grade"] == grade]
    return listing(rows, serializers.raw_receipt)


@bp.post("/raw-receipts/<receipt_id>/disposition")
@require("QATechnician", "QAManager")
def disposition(receipt_id):
    supplied = raw_body().get("override_justification")
    if supplied is not None and g.role != "QAManager":
        raise ApiError(
            "ERR_OVERRIDE_NOT_PERMITTED",
            "only a QAManager may supply override_justification",
        )
    body = read_body(DISPOSITION)
    receipt = db.get_or_404("raw_receipts", receipt_id)
    if receipt["status"] != "PENDING_INSPECTION":
        raise ApiError(
            "ERR_RECEIPT_NOT_PENDING", "the load is not PENDING_INSPECTION"
        )
    justification = body["override_justification"]
    if body["decision"] == "ACCEPT":
        overridden = g.role == "QAManager" and justification is not None
        if receipt["temp_grade"] == "OUT_OF_SPEC" and not overridden:
            raise ApiError(
                "ERR_RECEIPT_TEMP_OUT_OF_SPEC",
                "an OUT_OF_SPEC load needs a QAManager override justification",
            )
        trim = body["trim_loss_lb"]
        if trim is None:
            trim = Decimal(0)
        if trim < 0 or trim > receipt["net_weight_lb"]:
            raise ApiError(
                "ERR_TRIM_LOSS_EXCEEDS_NET",
                "trim_loss_lb must be between 0 and net_weight_lb",
            )
        accepted = q2(receipt["net_weight_lb"] - trim)
        receipt["trim_loss_lb"] = trim
        receipt["accepted_lb"] = accepted
        receipt["remaining_lb"] = accepted
        receipt["status"] = "ACCEPTED"
    else:
        receipt["status"] = "REJECTED"
    if justification is not None:
        receipt["override_justification"] = justification
    receipt["dispositioned_by_user_id"] = actor()
    db.touch(receipt)
    lot = db.find("grower_lots", receipt["grower_lot_id"])
    if lot is not None:
        lots.recompute_trailing(lot)
    return object_response(serializers.raw_receipt(receipt))
