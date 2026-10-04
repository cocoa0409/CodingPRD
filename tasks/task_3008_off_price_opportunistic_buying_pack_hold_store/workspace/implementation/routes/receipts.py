"""Receipts: open, record line quantities, complete with variance valuation."""
from flask import Blueprint, request

import errors as err
from errors import ApiError
from db import db, now
from middleware import require
from response import success, success_list
from services.calc import (
    get_body, validate_body, require_range, new_common, touch, get_or_404,
    find_by, paginate, serialize, sorted_list, round_half_up, new_id, wall_now_iso,
    recompute_spend, refresh_availability,
)

bp = Blueprint("receipts", __name__)

RECEIPT_ROLES = ("WarehouseClerk", "InventoryPlanner", "PlanningLead")


@bp.post("/receipts")
def create_receipt():
    require(("WarehouseClerk",))
    vals = validate_body(get_body(required=True), {
        "lot_id": ("str", True),
        "warehouse_id": ("str", True),
    })
    lot = get_or_404("lots", vals["lot_id"], "lot not found")
    get_or_404("warehouses", vals["warehouse_id"], "warehouse not found")
    if lot["status"] != "ACCEPTED":
        raise err.invalid_state("receipts can be opened only against an ACCEPTED lot")
    receipt = new_common()
    receipt.update({
        "lot_id": lot["id"],
        "warehouse_id": vals["warehouse_id"],
        "receipt_date": now(),
        "status": "OPEN",
    })
    db["receipts"][receipt["id"]] = receipt
    for line in sorted_list(find_by("lot_lines", "lot_id", lot["id"])):
        rl = {
            "id": new_id(),
            "created_at": wall_now_iso(),
            "receipt_id": receipt["id"],
            "lot_line_id": line["id"],
            "declared_qty": line["quantity"],
            "received_qty": None,
            "variance_qty": None,
            "variance_value_cents": None,
            "extended_cost_cents": None,
        }
        db["receipt_lines"][rl["id"]] = rl
    return success(serialize("receipt", receipt), status=201)


@bp.get("/receipts")
def list_receipts():
    require(RECEIPT_ROLES)
    filters = {k: request.args.get(k) for k in ("lot_id", "warehouse_id", "status")}
    page, limit, offset, total = paginate(list(db["receipts"].values()), filters)
    return success_list([serialize("receipt", r) for r in page], limit, offset, total)


@bp.get("/receipts/<rid>")
def get_receipt(rid):
    require(RECEIPT_ROLES)
    return success(serialize("receipt", get_or_404("receipts", rid)))


@bp.get("/receipts/<rid>/receipt-lines")
def receipt_lines(rid):
    require(RECEIPT_ROLES)
    get_or_404("receipts", rid)
    page, limit, offset, total = paginate(find_by("receipt_lines", "receipt_id", rid))
    return success_list([serialize("receipt_line", l) for l in page], limit, offset, total)


@bp.patch("/receipts/<rid>/lines/<line_id>")
def record_received(rid, line_id):
    require(("WarehouseClerk",))
    receipt = get_or_404("receipts", rid)
    line = db["receipt_lines"].get(line_id)
    if line is None or line["receipt_id"] != rid:
        raise err.not_found("receipt line not found")
    vals = validate_body(get_body(required=True), {"received_qty": ("int", True)})
    if receipt["status"] != "OPEN":
        raise err.invalid_state("received quantities can be recorded only while the receipt is OPEN")
    if vals["received_qty"] < 0 or vals["received_qty"] > line["declared_qty"]:
        raise ApiError("ERR_RECEIPT_LINE_QTY_INVALID",
                       "received_qty must lie within [0, declared_qty]")
    line["received_qty"] = vals["received_qty"]
    return success(serialize("receipt_line", line))


@bp.post("/receipts/<rid>/complete")
def complete_receipt(rid):
    require(("WarehouseClerk",))
    receipt = get_or_404("receipts", rid)
    get_body()
    if receipt["status"] != "OPEN":
        raise err.invalid_state("only an OPEN receipt can be completed")
    lot = db["lots"][receipt["lot_id"]]
    lines = sorted_list(find_by("receipt_lines", "receipt_id", rid))
    if any(l["received_qty"] is None for l in lines):
        raise ApiError("ERR_RECEIPT_LINE_QTY_INVALID",
                       "every receipt line must have received_qty recorded")
    landed = lot["landed_cost_cents"] or 0
    for line in lines:
        line["variance_qty"] = line["declared_qty"] - line["received_qty"]
        line["extended_cost_cents"] = round_half_up(
            line["received_qty"] * landed / lot["unit_count"])
        line["variance_value_cents"] = round_half_up(
            line["variance_qty"] * landed / lot["unit_count"])
    receipt["status"] = "RECEIVED"
    touch(receipt)
    # one shrink case per short line
    for line in lines:
        if line["variance_qty"] > 0:
            case = new_common()
            case.update({
                "store_id": None,
                "store_sku_id": None,
                "lot_id": lot["id"],
                "shrink_type": "MIXED_LOT_SHORTAGE" if lot["mixed_lot"] else "UNSCANNED_UNIT",
                "merge_mode": "HIGH_VALUE_SORT" if lot["mixed_lot"] else "FIFO",
                "units_lost": 0,
                "units_untraceable": line["variance_qty"],
                "shrink_value_cents": None,
                "status": "OPEN",
            })
            db["shrink_cases"][case["id"]] = case
    season = db["seasons"].get(lot["season_id"])
    if season is not None:
        recompute_spend(season)
        refresh_availability(season)
        touch(season)
    return success(serialize("receipt", receipt))
