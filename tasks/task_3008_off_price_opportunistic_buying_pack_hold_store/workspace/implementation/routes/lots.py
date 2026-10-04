"""Lots and lot lines: registration, evaluation, adjudication, reverse lookups."""
from flask import Blueprint, request

import errors as err
from errors import ApiError
from db import db, now
from middleware import require, enforce_discretion
from response import success, success_list
from services.calc import (
    LOT_TYPES, DISPOSITIONS, DEPARTMENTS, FREIGHT_SURCHARGE_CENTS_PER_LOT,
    get_body, validate_body, require_range, new_common, touch, get_or_404,
    find_by, check_unique, paginate, serialize, parse_date,
    refresh_availability, deal_quality_score, MISSING,
)
from middleware import is_senior_buyer

bp = Blueprint("lots", __name__)

LOT_READ_ROLES = ("Buyer", "PlanningLead", "AllocationManager",
                  "InventoryPlanner", "PricingAnalyst", "WarehouseClerk")


def _visible(lot, user_id, role):
    if role == "Buyer" and not is_senior_buyer(user_id, role):
        vendor = db["vendors"].get(lot["vendor_id"])
        if vendor and vendor["discretion_level"] in ("CONFIDENTIAL", "QUIET"):
            return False
    return True


def _get_visible_lot(lot_id, user_id, role):
    lot = get_or_404("lots", lot_id)
    if not _visible(lot, user_id, role):
        raise err.not_found("lot not found")
    return lot


def _check_target_season_draft(vals, season_id):
    target_id = vals.get("target_season_id", MISSING)
    if target_id is MISSING or target_id is None:
        # A required field is missing -> request well-formedness failure (§2.9).
        raise err.invalid_request("target_season_id is required for a PACKAWAY disposition")
    target = db["seasons"].get(target_id)
    if target is None:
        raise ApiError("ERR_TARGET_SEASON_NOT_DRAFT",
                       "target season must exist, be DRAFT, and differ from the buying season")
    if target["status"] != "DRAFT" or target_id == season_id:
        raise ApiError("ERR_TARGET_SEASON_NOT_DRAFT",
                       "target season must exist, be DRAFT, and differ from the buying season")


# ------------------------------------------------------------------- lots
@bp.post("/lots")
def create_lot():
    require(("Buyer", "PlanningLead"))
    vals = validate_body(get_body(required=True), {
        "lot_code": ("str", True),
        "vendor_id": ("str", True),
        "season_id": ("str", True),
        "lot_type": ("enum", True, LOT_TYPES),
        "disposition": ("enum", True, DISPOSITIONS),
        "asking_price_cents": ("int", True),
        "mixed_lot": ("bool", False),
        "unit_count": ("int", True),
        "expected_sell_through_pct": ("float", True),
        "estimated_unit_retail_cents": ("int", True),
        "offer_expires_at": ("datetime", True),
        "target_season_id": ("str", False),
    })
    # existence of FK references (priority 3)
    get_or_404("vendors", vals["vendor_id"], "vendor not found")
    get_or_404("seasons", vals["season_id"], "season not found")
    require_range(vals["asking_price_cents"], lo=0, lo_exclusive=True, field="asking_price_cents")
    require_range(vals["unit_count"], lo=0, lo_exclusive=True, field="unit_count")
    require_range(vals["expected_sell_through_pct"], lo=0, hi=1, lo_exclusive=True,
                  field="expected_sell_through_pct")
    require_range(vals["estimated_unit_retail_cents"], lo=0, lo_exclusive=True,
                  field="estimated_unit_retail_cents")
    check_unique("lots", "lot_code", vals["lot_code"], "lot_code already exists")
    if vals["disposition"] == "PACKAWAY":
        _check_target_season_draft(vals, vals["season_id"])
    elif "target_season_id" in vals and vals["target_season_id"] is not None:
        get_or_404("seasons", vals["target_season_id"], "target season not found")
    lot = new_common()
    lot.update(vals)
    lot["mixed_lot"] = vals.get("mixed_lot", False)
    lot["target_season_id"] = vals.get("target_season_id")
    lot.update({
        "landed_cost_cents": None,
        "deal_quality_score": None,
        "status": "OFFERED",
        "cancel_reason": None,
    })
    db["lots"][lot["id"]] = lot
    return success(serialize("lot", lot), status=201)


@bp.get("/lots")
def list_lots():
    user_id, role = require(LOT_READ_ROLES)
    lots = [l for l in db["lots"].values() if _visible(l, user_id, role)]
    filters = {k: request.args.get(k) for k in
               ("season_id", "target_season_id", "vendor_id", "status", "disposition")}
    page, limit, offset, total = paginate(lots, filters)
    return success_list([serialize("lot", l) for l in page], limit, offset, total)


@bp.get("/lots/<lot_id>")
def get_lot(lot_id):
    user_id, role = require(LOT_READ_ROLES)
    lot = _get_visible_lot(lot_id, user_id, role)
    return success(serialize("lot", lot))


@bp.post("/lots/<lot_id>/evaluate")
def evaluate_lot(lot_id):
    user_id, role = require(("Buyer",))
    lot = get_or_404("lots", lot_id)
    vals = validate_body(get_body(), {"negotiated_price_cents": ("int", False)})
    # The system cancels a lapsed unevaluated offer on read of any action.
    if lot["status"] == "OFFERED" and now() >= lot["offer_expires_at"]:
        lot["status"] = "CANCELLED"
        lot["cancel_reason"] = "OFFER_EXPIRED"
        touch(lot)
        raise ApiError("ERR_OFFER_EXPIRED", "the offer has expired")
    if lot["status"] not in ("OFFERED", "EVALUATED"):
        raise err.invalid_state("only an OFFERED or EVALUATED lot can be evaluated")
    if now() >= lot["offer_expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED", "the offer has expired")
    enforce_discretion(lot, user_id, role, db["vendors"])
    if "negotiated_price_cents" in vals:
        require_range(vals["negotiated_price_cents"], lo=0, lo_exclusive=True,
                      field="negotiated_price_cents")
    base = vals.get("negotiated_price_cents", lot["asking_price_cents"])
    lot["landed_cost_cents"] = base + FREIGHT_SURCHARGE_CENTS_PER_LOT
    vendor = db["vendors"][lot["vendor_id"]]
    lot["deal_quality_score"] = deal_quality_score(lot, vendor, lot["landed_cost_cents"])
    lot["status"] = "EVALUATED"
    touch(lot)
    return success(serialize("lot", lot))


@bp.post("/lots/<lot_id>/accept")
def accept_lot(lot_id):
    user_id, role = require(("Buyer",))
    lot = get_or_404("lots", lot_id)
    vals = validate_body(get_body(required=True),
                         {"expected_season_version": ("int", True)})
    if lot["status"] != "EVALUATED":
        raise err.invalid_state("only an EVALUATED lot can be accepted")
    season = db["seasons"][lot["season_id"]]
    if vals["expected_season_version"] != season["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_season_version does not match the season version")
    if now() >= lot["offer_expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED", "the offer has expired")
    enforce_discretion(lot, user_id, role, db["vendors"])
    # Admission reads the season's availability read model (§3.1), refreshed on
    # the season row.
    refresh_availability(season)
    if lot["disposition"] == "IMMEDIATE":
        if lot["landed_cost_cents"] > season["forward_available_cents"]:
            raise ApiError("ERR_OTB_FORWARD_EXCEEDED",
                           "landed cost exceeds forward open-to-buy availability")
    else:
        if lot["landed_cost_cents"] > season["packaway_available_cents"]:
            raise ApiError("ERR_OTB_PACKAWAY_EXCEEDED",
                           "landed cost exceeds packaway open-to-buy availability")
        # Acceptance re-verifies existence and distinctness of the target; the
        # still-DRAFT requirement is rechecked at packaway hold creation (§3.2).
        target = db["seasons"].get(lot["target_season_id"])
        if target is None or lot["target_season_id"] == lot["season_id"]:
            raise ApiError("ERR_TARGET_SEASON_NOT_DRAFT",
                           "target season must exist, be DRAFT, and differ from the buying season")
    if lot["disposition"] == "IMMEDIATE":
        season["committed_forward_cents"] += lot["landed_cost_cents"]
    else:
        season["committed_packaway_cents"] += lot["landed_cost_cents"]
    refresh_availability(season)
    touch(season)
    lot["status"] = "ACCEPTED"
    touch(lot)
    return success(serialize("lot", lot))


@bp.post("/lots/<lot_id>/pass")
def pass_lot(lot_id):
    user_id, role = require(("Buyer",))
    lot = get_or_404("lots", lot_id)
    get_body()
    if lot["status"] != "EVALUATED":
        raise err.invalid_state("only an EVALUATED lot can be passed")
    enforce_discretion(lot, user_id, role, db["vendors"])
    lot["status"] = "PASSED"
    touch(lot)
    return success(serialize("lot", lot))


@bp.post("/lots/<lot_id>/cancel")
def cancel_lot(lot_id):
    require(("Buyer", "PlanningLead"))
    lot = get_or_404("lots", lot_id)
    from services.calc import CANCEL_REASONS
    vals = validate_body(get_body(required=True),
                         {"cancel_reason": ("enum", True, CANCEL_REASONS)})
    if lot["status"] not in ("OFFERED", "EVALUATED"):
        raise err.invalid_state("only an OFFERED or EVALUATED lot can be cancelled")
    lot["status"] = "CANCELLED"
    lot["cancel_reason"] = vals["cancel_reason"]
    touch(lot)
    return success(serialize("lot", lot))


# ------------------------------------------------------------------- lot lines
@bp.post("/lots/<lot_id>/lot-lines")
def create_lot_line(lot_id):
    require(("Buyer", "PlanningLead"))
    lot = get_or_404("lots", lot_id)
    if lot["status"] not in ("OFFERED", "EVALUATED"):
        raise err.invalid_state("lot lines can be added only while the lot is OFFERED or EVALUATED")
    vals = validate_body(get_body(required=True), {
        "style_code": ("str", True),
        "department": ("enum", True, DEPARTMENTS),
        "quantity": ("int", True),
        "unit_cost_cents": ("int", True),
        "compare_at_claim_cents": ("int", True),
        "target_retail_cents": ("int", True),
    })
    require_range(vals["quantity"], lo=0, lo_exclusive=True, field="quantity")
    require_range(vals["unit_cost_cents"], lo=0, field="unit_cost_cents")
    require_range(vals["compare_at_claim_cents"], lo=0, lo_exclusive=True,
                  field="compare_at_claim_cents")
    require_range(vals["target_retail_cents"], lo=0, lo_exclusive=True,
                  field="target_retail_cents")
    line = new_common()
    line.update(vals)
    line["lot_id"] = lot_id
    db["lot_lines"][line["id"]] = line
    return success(serialize("lot_line", line), status=201)


@bp.get("/lots/<lot_id>/lot-lines")
def list_lot_lines(lot_id):
    require(LOT_READ_ROLES)
    get_or_404("lots", lot_id)
    page, limit, offset, total = paginate(find_by("lot_lines", "lot_id", lot_id))
    return success_list([serialize("lot_line", l) for l in page], limit, offset, total)


@bp.get("/lot-lines/<line_id>")
def get_lot_line(line_id):
    require(LOT_READ_ROLES)
    return success(serialize("lot_line", get_or_404("lot_lines", line_id)))


# ------------------------------------------------------------------- lot reverse reachability
@bp.get("/lots/<lot_id>/packaway-holds")
def lot_holds(lot_id):
    require(("InventoryPlanner", "PlanningLead", "WarehouseClerk"))
    get_or_404("lots", lot_id)
    page, limit, offset, total = paginate(find_by("holds", "lot_id", lot_id))
    return success_list([serialize("hold", h) for h in page], limit, offset, total)


@bp.get("/lots/<lot_id>/allocation-plans")
def lot_plans(lot_id):
    require(("AllocationManager", "PlanningLead", "Buyer"))
    get_or_404("lots", lot_id)
    page, limit, offset, total = paginate(find_by("plans", "lot_id", lot_id))
    return success_list([serialize("plan", p) for p in page], limit, offset, total)


@bp.get("/lots/<lot_id>/receipts")
def lot_receipts(lot_id):
    require(("WarehouseClerk", "PlanningLead", "InventoryPlanner"))
    get_or_404("lots", lot_id)
    page, limit, offset, total = paginate(find_by("receipts", "lot_id", lot_id))
    return success_list([serialize("receipt", r) for r in page], limit, offset, total)


@bp.get("/lots/<lot_id>/shrink-cases")
def lot_shrink_cases(lot_id):
    require(("ShrinkAuditor", "PlanningLead"))
    get_or_404("lots", lot_id)
    page, limit, offset, total = paginate(find_by("shrink_cases", "lot_id", lot_id))
    return success_list([serialize("shrink_case", c) for c in page], limit, offset, total)


@bp.get("/lots/<lot_id>/liquidation-orders")
def lot_liquidation_orders(lot_id):
    require(("PlanningLead", "StoreOpsLead"))
    get_or_404("lots", lot_id)
    page, limit, offset, total = paginate(find_by("liquidation_orders", "lot_id", lot_id))
    return success_list([serialize("liquidation_order", o) for o in page], limit, offset, total)


# ------------------------------------------------------------------- lot-line reverse reachability
@bp.get("/lot-lines/<line_id>/tickets")
def line_tickets(line_id):
    require(("PricingAnalyst", "PlanningLead", "StoreOpsLead"))
    get_or_404("lot_lines", line_id)
    page, limit, offset, total = paginate(find_by("tickets", "lot_line_id", line_id))
    return success_list([serialize("ticket", t) for t in page], limit, offset, total)


@bp.get("/lot-lines/<line_id>/store-skus")
def line_store_skus(line_id):
    require(("StoreOpsLead", "AllocationManager", "PlanningLead"))
    get_or_404("lot_lines", line_id)
    page, limit, offset, total = paginate(find_by("store_skus", "lot_line_id", line_id))
    return success_list([serialize("store_sku", s) for s in page], limit, offset, total)


@bp.get("/lot-lines/<line_id>/receipt-lines")
def line_receipt_lines(line_id):
    require(("WarehouseClerk", "PlanningLead"))
    get_or_404("lot_lines", line_id)
    page, limit, offset, total = paginate(find_by("receipt_lines", "lot_line_id", line_id))
    return success_list([serialize("receipt_line", r) for r in page], limit, offset, total)
