"""Shrink cases: filing, confirmation with valuation, voiding."""
from flask import Blueprint, request

import errors as err
from errors import ApiError
from db import db
from middleware import require
from response import success, success_list
from services.calc import (
    SHRINK_TYPES, MERGE_MODES,
    get_body, validate_body, require_range, new_common, touch, get_or_404,
    paginate, serialize, sorted_list, round_half_up,
)

bp = Blueprint("shrink", __name__)

SHRINK_ROLES = ("ShrinkAuditor", "PlanningLead", "StoreOpsLead")


@bp.post("/shrink-cases")
def create_shrink_case():
    require(("ShrinkAuditor", "StoreOpsLead"))
    vals = validate_body(get_body(required=True), {
        "store_id": ("str", False),
        "store_sku_id": ("str", False),
        "lot_id": ("str", False),
        "shrink_type": ("enum", True, SHRINK_TYPES),
        "merge_mode": ("enum", False, MERGE_MODES),
        "units_lost": ("int", True),
        "units_untraceable": ("int", True),
    })
    get_or_404("stores", vals["store_id"], "store not found") \
        if vals.get("store_id") is not None else None
    store_sku = None
    lot = None
    if vals.get("store_sku_id") is not None:
        store_sku = get_or_404("store_skus", vals["store_sku_id"], "store sku not found")
    if vals.get("lot_id") is not None:
        lot = get_or_404("lots", vals["lot_id"], "lot not found")
    require_range(vals["units_lost"], lo=0, field="units_lost")
    require_range(vals["units_untraceable"], lo=0, field="units_untraceable")
    if vals["units_lost"] == 0 and vals["units_untraceable"] == 0:
        raise err.invalid_request("units_lost and units_untraceable cannot both be 0")
    if vals["units_untraceable"] > 0:
        # Untraceable units cannot be traced to any store SKU.
        if vals.get("store_sku_id") is not None:
            raise err.invalid_request(
                "store_sku_id must be omitted when units_untraceable > 0")
    else:
        # Traced units write off against a specific store SKU of a lot.
        if vals.get("store_sku_id") is None or vals.get("lot_id") is None:
            raise err.invalid_request(
                "store_sku_id and lot_id are required for traced shrink")
    # merge policy: mixed lots force HIGH_VALUE_SORT
    if lot is None:
        merge_mode = vals.get("merge_mode", "FIFO")
    else:
        merge_mode = "HIGH_VALUE_SORT" if lot["mixed_lot"] else vals.get("merge_mode", "FIFO")
    case = new_common()
    case.update({
        "store_id": vals.get("store_id"),
        "store_sku_id": vals.get("store_sku_id") if vals["units_untraceable"] == 0 else None,
        "lot_id": vals.get("lot_id"),
        "shrink_type": vals["shrink_type"],
        "merge_mode": merge_mode,
        "units_lost": vals["units_lost"],
        "units_untraceable": vals["units_untraceable"],
        "shrink_value_cents": None,
        "status": "OPEN",
    })
    db["shrink_cases"][case["id"]] = case
    return success(serialize("shrink_case", case), status=201)


@bp.get("/shrink-cases")
def list_shrink_cases():
    require(SHRINK_ROLES)
    filters = {k: request.args.get(k) for k in
               ("store_id", "lot_id", "store_sku_id", "shrink_type", "status")}
    page, limit, offset, total = paginate(list(db["shrink_cases"].values()), filters)
    return success_list([serialize("shrink_case", c) for c in page], limit, offset, total)


@bp.get("/shrink-cases/<cid>")
def get_shrink_case(cid):
    require(SHRINK_ROLES)
    return success(serialize("shrink_case", get_or_404("shrink_cases", cid)))


def _untraceable_lot(case):
    """Resolve the lot for an untraceable case: via the store's SKUs' lines, or
    failing that the unique lot of the store's stock."""
    if case.get("lot_id"):
        return db["lots"].get(case["lot_id"])
    store_id = case.get("store_id")
    if store_id:
        lot_ids = set()
        for sku in db["store_skus"].values():
            if sku["store_id"] == store_id:
                line = db["lot_lines"].get(sku["lot_line_id"])
                if line:
                    lot_ids.add(line["lot_id"])
        if len(lot_ids) == 1:
            return db["lots"].get(next(iter(lot_ids)))
    return None


@bp.post("/shrink-cases/<cid>/confirm")
def confirm_shrink_case(cid):
    require(("ShrinkAuditor",))
    case = get_or_404("shrink_cases", cid)
    get_body()
    if case["status"] != "OPEN":
        raise err.invalid_state("only an OPEN shrink case can be confirmed")
    if case["store_sku_id"] is not None:
        sku = db["store_skus"][case["store_sku_id"]]
        if case["units_lost"] > sku["units_on_hand"]:
            raise ApiError("ERR_SHRINK_EXCEEDS_ON_HAND",
                           "units_lost exceeds the store SKU's units_on_hand")
        lot = db["lots"][case["lot_id"]]
        unit_value = round_half_up((lot["landed_cost_cents"] or 0) / lot["unit_count"])
        case["shrink_value_cents"] = case["units_lost"] * unit_value
        sku["units_on_hand"] -= case["units_lost"]
        if sku["units_on_hand"] == 0:
            sku["status"] = "SOLD_OUT"
        touch(sku)
    else:
        lot = _untraceable_lot(case)
        lines = sorted_list([l for l in db["lot_lines"].values()
                             if lot is not None and l["lot_id"] == lot["id"]])
        if case["merge_mode"] == "HIGH_VALUE_SORT":
            lines.sort(key=lambda l: -l["compare_at_claim_cents"])
        remaining = case["units_untraceable"]
        value = 0
        for line in lines:
            if remaining <= 0:
                break
            draw = min(remaining, line["quantity"])
            value += draw * line["unit_cost_cents"]
            remaining -= draw
        case["shrink_value_cents"] = value
    case["status"] = "CONFIRMED"
    touch(case)
    return success(serialize("shrink_case", case))


@bp.post("/shrink-cases/<cid>/void")
def void_shrink_case(cid):
    require(("ShrinkAuditor",))
    case = get_or_404("shrink_cases", cid)
    get_body()
    if case["status"] != "OPEN":
        raise err.invalid_state("only an OPEN shrink case can be voided")
    case["status"] = "VOIDED"
    touch(case)
    return success(serialize("shrink_case", case))
