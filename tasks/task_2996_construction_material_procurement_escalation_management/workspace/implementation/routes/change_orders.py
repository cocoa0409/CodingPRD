"""ChangeOrderRequest endpoints (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import serial
from auth import authorize, current_user_id
from envelope import created, ok, paginated
from errors import ApiError
from shapes import Field, validate
from store import ordered, store
from util import D, q2

bp = Blueprint("change_orders", __name__)

CHANGE_ORDER_FIELDS = [
    Field("purchase_commitment_id", "string", required=True),
    Field("claimed_amount", "number", required=True, minimum=0, max_dp=2),
    Field("narrative", "string", required=True, min_len=1, max_len=2000),
]

DISPOSITION_FIELDS = [
    Field("disposition", "enum", required=True, choices=("APPROVED", "REJECTED")),
    Field("owner_note", "string", nullable=True, allow_blank=True),
]


def _final_gross(commitment):
    if commitment["escalation_variant"] != "FINAL":
        return Decimal("0.00")
    return q2(commitment["escalation_accrued"])


@bp.post("/procurement/change-order-requests")
@authorize("BuyoutManager")
def create_change_order():
    body = validate(CHANGE_ORDER_FIELDS)
    commitment = domain.get_commitment(body["purchase_commitment_id"])
    gross = _final_gross(commitment)
    if gross <= 0 or D(body["claimed_amount"]) <= 0:
        raise ApiError("ERR_CLAIM_NOT_SUBSTANTIATED")

    fee_pct, fee_amount, substantiated = calc.substantiation(gross, body["claimed_amount"])
    row = store.new_row()
    row["purchase_commitment_id"] = commitment["id"]
    row["claimed_amount"] = body["claimed_amount"]
    row["narrative"] = body["narrative"]
    row["prepared_by_user_id"] = current_user_id()
    row["submitted_by_user_id"] = None
    row["gross_documented_amount"] = gross
    row["admin_fee_pct"] = fee_pct
    row["admin_fee_amount"] = fee_amount
    row["substantiated_amount"] = substantiated
    row["owner_note"] = None
    row["status"] = "PREPARED"
    store.change_orders[row["id"]] = row
    return created(serial.change_order(row))


@bp.get("/procurement/change-order-requests/<change_order_id>")
@authorize("BuyoutManager", "ProjectExecutive", "OwnerRep")
def read_change_order(change_order_id):
    row = domain.get_change_order(change_order_id)
    return ok(serial.change_order(row))


@bp.get("/procurement/change-order-requests")
@authorize("BuyoutManager", "ProjectExecutive", "OwnerRep")
def list_change_orders():
    args = request.args
    commitment_id = domain.string_filter(args, "purchase_commitment_id")
    status = domain.string_filter(args, "status")
    rows = []
    for row in ordered(list(store.change_orders.values())):
        if commitment_id is not None and row["purchase_commitment_id"] != commitment_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paginated(rows, serial.change_order)


@bp.post("/procurement/change-order-requests/<change_order_id>/submit")
@authorize("BuyoutManager")
def submit_change_order(change_order_id):
    validate([])
    row = domain.get_change_order(change_order_id)
    if current_user_id() == row["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if row["status"] != "PREPARED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    commitment = store.commitments[row["purchase_commitment_id"]]
    if _final_gross(commitment) <= 0:
        raise ApiError("ERR_CLAIM_NOT_SUBSTANTIATED")
    row["status"] = "SUBMITTED"
    row["submitted_by_user_id"] = current_user_id()
    store.touch(row)
    return ok(serial.change_order(row))


@bp.post("/procurement/change-order-requests/<change_order_id>/disposition")
@authorize("OwnerRep")
def disposition_change_order(change_order_id):
    body = validate(DISPOSITION_FIELDS)
    row = domain.get_change_order(change_order_id)
    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if "owner_note" in body:
        row["owner_note"] = body["owner_note"]
    row["status"] = (
        "OWNER_APPROVED" if body["disposition"] == "APPROVED" else "OWNER_REJECTED"
    )
    store.touch(row)
    return ok(serial.change_order(row))
