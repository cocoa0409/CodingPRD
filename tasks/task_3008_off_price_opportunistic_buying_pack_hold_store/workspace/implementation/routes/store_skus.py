"""Store SKUs: manual placement, depletion, reverse lookups."""
from flask import Blueprint, request

import errors as err
from errors import ApiError
from db import db, now
from middleware import require
from response import success, success_list
from services.calc import (
    LIVE_SKU_STATUSES,
    get_body, validate_body, require_range, new_common, touch, get_or_404,
    find_by, paginate, serialize,
)

bp = Blueprint("store_skus", __name__)

SKU_ROLES = ("StoreOpsLead", "AllocationManager", "PlanningLead", "ShrinkAuditor")


def _store_units_in_use(store_id):
    return sum(s["units_on_hand"] for s in db["store_skus"].values()
               if s["store_id"] == store_id and s["status"] in LIVE_SKU_STATUSES)


@bp.post("/store-skus")
def create_store_sku():
    require(("StoreOpsLead", "AllocationManager"))
    vals = validate_body(get_body(required=True), {
        "store_id": ("str", True),
        "lot_line_id": ("str", True),
        "ticket_id": ("str", True),
        "season_id": ("str", True),
        "units_on_hand": ("int", True),
    })
    store = get_or_404("stores", vals["store_id"], "store not found")
    line = get_or_404("lot_lines", vals["lot_line_id"], "lot line not found")
    ticket = get_or_404("tickets", vals["ticket_id"], "ticket not found")
    get_or_404("seasons", vals["season_id"], "season not found")
    require_range(vals["units_on_hand"], lo=0, lo_exclusive=True, field="units_on_hand")
    if ticket["status"] != "ACTIVE" or ticket["lot_line_id"] != line["id"] \
            or ticket["zone_code"] != store["zone_code"]:
        raise ApiError("ERR_TICKET_NOT_ISSUED",
                       "an ACTIVE ticket for the store's zone is required")
    if _store_units_in_use(store["id"]) + vals["units_on_hand"] > store["storage_capacity_units"]:
        raise ApiError("ERR_STORE_OVER_CAPACITY", "store storage capacity exceeded")
    sku = new_common()
    sku.update({
        "store_id": store["id"],
        "lot_line_id": line["id"],
        "ticket_id": ticket["id"],
        "season_id": vals["season_id"],
        "allocation_plan_id": None,
        "units_on_hand": vals["units_on_hand"],
        "floor_date": now(),
        "weeks_on_floor": 0,
        "markdown_step": 0,
        "current_price_cents": ticket["ticket_retail_cents"],
        "status": "ON_FLOOR",
    })
    db["store_skus"][sku["id"]] = sku
    return success(serialize("store_sku", sku), status=201)


@bp.get("/store-skus")
def list_store_skus():
    require(SKU_ROLES)
    filters = {k: request.args.get(k) for k in
               ("store_id", "lot_line_id", "season_id", "allocation_plan_id", "status")}
    page, limit, offset, total = paginate(list(db["store_skus"].values()), filters)
    return success_list([serialize("store_sku", s) for s in page], limit, offset, total)


@bp.get("/store-skus/<sid>")
def get_store_sku(sid):
    require(SKU_ROLES)
    return success(serialize("store_sku", get_or_404("store_skus", sid)))


@bp.post("/store-skus/<sid>/deplete")
def deplete_store_sku(sid):
    require(("StoreOpsLead",))
    sku = get_or_404("store_skus", sid)
    vals = validate_body(get_body(required=True), {"units_sold": ("int", True)})
    require_range(vals["units_sold"], lo=0, lo_exclusive=True, field="units_sold")
    if sku["status"] not in ("ON_FLOOR", "MARKED_DOWN", "CLEARANCE"):
        raise err.invalid_state("depletion is admissible only from a live state")
    if vals["units_sold"] > sku["units_on_hand"]:
        raise ApiError("ERR_NEGATIVE_ON_HAND", "units_sold exceeds units_on_hand")
    sku["units_on_hand"] -= vals["units_sold"]
    if sku["units_on_hand"] == 0:
        sku["status"] = "SOLD_OUT"
    touch(sku)
    return success(serialize("store_sku", sku))


@bp.get("/store-skus/<sid>/markdown-events")
def sku_markdown_events(sid):
    require(("StoreOpsLead", "PlanningLead", "PricingAnalyst"))
    get_or_404("store_skus", sid)
    page, limit, offset, total = paginate(find_by("markdown_events", "store_sku_id", sid))
    return success_list([serialize("markdown_event", e) for e in page], limit, offset, total)


@bp.get("/store-skus/<sid>/shrink-cases")
def sku_shrink_cases(sid):
    require(("ShrinkAuditor", "PlanningLead", "StoreOpsLead"))
    get_or_404("store_skus", sid)
    page, limit, offset, total = paginate(find_by("shrink_cases", "store_sku_id", sid))
    return success_list([serialize("shrink_case", c) for c in page], limit, offset, total)
