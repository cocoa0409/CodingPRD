"""Product sales contracts: create, read, list, record deliveries."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import require_roles
from calc import FEEDSTOCK_QUOTA_DAYS, MAX_DELIVERY_WINDOW_DAYS
from envelope import success_list, success_obj
from errors import fail
from store import db, get_clock, new_id, stamp_new, to_jsonable, touch
from validate import (body_dict, forbid_fields, get_decimal, paginate,
                      req_datetime, req_int, req_str, sort_created)

bp = Blueprint("sales", __name__)

PRODUCTS = ("SOY_MEAL", "SOY_OIL", "BIODIESEL_FEEDSTOCK")


@bp.post("/api/product-sales-contracts")
def create_sales_contract():
    require_roles("ProductMerchandiser")
    body = body_dict()
    # Body FKs (priority 4).
    buyer = None
    if body.get("buyer_id") is not None:
        buyer = db["buyers"].get(body["buyer_id"])
        if buyer is None:
            fail("ERR_BUYER_NOT_FOUND", "buyer_id does not resolve")
    plant = None
    if body.get("plant_id") is not None:
        plant = db["plants"].get(body["plant_id"])
        if plant is None:
            fail("ERR_PLANT_NOT_FOUND", "plant_id does not resolve")
    if buyer is None:
        fail("ERR_INVALID_REQUEST", "buyer_id is required")
    if plant is None:
        fail("ERR_INVALID_REQUEST", "plant_id is required")
    product = body.get("product")
    if product not in PRODUCTS:
        fail("ERR_INVALID_REQUEST",
             "product must be SOY_MEAL, SOY_OIL or BIODIESEL_FEEDSTOCK")
    # Temporal (priority 7): window well-formed (end > start, span <= 62 days).
    start = req_datetime(body, "delivery_window_start")
    end = req_datetime(body, "delivery_window_end")
    if end <= start or (end - start) > timedelta(days=MAX_DELIVERY_WINDOW_DAYS):
        fail("ERR_DELIVERY_WINDOW_INVALID",
             "window end must be after start and span at most 62 days")
    # Shape (priority 9): quantities and product-matched quality specs.
    qty = req_int(body, "quantity_lbs")
    if qty <= 0:
        fail("ERR_INVALID_REQUEST", "quantity_lbs must be > 0")
    price = req_int(body, "price_cents_per_lb")
    if price <= 0:
        fail("ERR_INVALID_REQUEST", "price_cents_per_lb must be > 0")
    min_protein = get_decimal(body, "min_protein_pct")
    max_ffa = get_decimal(body, "max_ffa_pct")
    if product == "SOY_MEAL":
        if min_protein is None:
            fail("ERR_INVALID_REQUEST", "min_protein_pct is required for SOY_MEAL")
        forbid_fields(body, ("max_ffa_pct",))
    else:
        if max_ffa is None:
            fail("ERR_INVALID_REQUEST",
                 "max_ffa_pct is required for SOY_OIL and BIODIESEL_FEEDSTOCK")
        forbid_fields(body, ("min_protein_pct",))
    # Capacity (priority 10): biodiesel feedstock quota per plant.
    if product == "BIODIESEL_FEEDSTOCK":
        used = sum(c["quantity_lbs"] for c in db["sales"].values()
                   if c["plant_id"] == plant["id"]
                   and c["product"] == "BIODIESEL_FEEDSTOCK"
                   and c["status"] in ("OPEN", "DELIVERING", "FULFILLED"))
        quota = (Decimal(plant["daily_refinery_capacity_lbs"])
                 * Decimal(plant["biodiesel_feedstock_share_pct"]) / Decimal(100)
                 * FEEDSTOCK_QUOTA_DAYS)
        if Decimal(used + qty) > quota:
            fail("ERR_FEEDSTOCK_QUOTA_EXCEEDED",
                 "biodiesel feedstock quota exceeded for this plant")
    # Referenced-entity state (priority 11): buyer must be ACTIVE.
    if buyer["status"] != "ACTIVE":
        fail("ERR_BUYER_NOT_ACTIVE", "buyer is not ACTIVE")
    rec = {
        "id": new_id(),
        "buyer_id": buyer["id"],
        "plant_id": plant["id"],
        "product": product,
        "quantity_lbs": qty,
        "price_cents_per_lb": price,
        "delivery_window_start": start,
        "delivery_window_end": end,
        "min_protein_pct": min_protein,
        "max_ffa_pct": max_ffa,
        "delivered_lbs": 0,
        "deliveries": [],
        "claim_cents": None,
        "status": "OPEN",
    }
    stamp_new(rec)
    db["sales"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


def _get_sales_or_404(sid):
    rec = db["sales"].get(sid)
    if rec is None:
        fail("ERR_SALES_CONTRACT_NOT_FOUND", "product sales contract not found")
    return rec


def _check_buyer_ownership(uid, role, contract):
    if role == "CommercialBuyer" and contract["buyer_id"] != uid:
        fail("ERR_FORBIDDEN",
             "CommercialBuyer callers may only access their own contracts")


@bp.get("/api/product-sales-contracts/<sid>")
def get_sales_contract(sid):
    uid, role = require_roles("PlatformAdmin", "ProductMerchandiser",
                              "CommercialBuyer")
    rec = _get_sales_or_404(sid)
    _check_buyer_ownership(uid, role, rec)
    return success_obj(to_jsonable(rec))


@bp.get("/api/product-sales-contracts")
def list_sales_contracts():
    uid, role = require_roles("PlatformAdmin", "ProductMerchandiser",
                              "CommercialBuyer")
    items = sort_created(list(db["sales"].values()))
    if role == "CommercialBuyer":
        items = [c for c in items if c["buyer_id"] == uid]
    buyer_id = request.args.get("buyer_id")
    plant_id = request.args.get("plant_id")
    if buyer_id is not None:
        items = [c for c in items if c["buyer_id"] == buyer_id]
    if plant_id is not None:
        items = [c for c in items if c["plant_id"] == plant_id]
    page, limit, offset, total = paginate(items)
    return success_list([to_jsonable(c) for c in page], limit, offset, total)


@bp.post("/api/product-sales-contracts/<sid>/deliver")
def record_delivery(sid):
    require_roles("ProductMerchandiser")
    rec = _get_sales_or_404(sid)
    body = body_dict()
    # State (priority 6): only OPEN/DELIVERING contracts accept deliveries.
    if rec["status"] not in ("OPEN", "DELIVERING"):
        fail("ERR_INVALID_STATE", "contract does not accept deliveries")
    delivery_date = req_datetime(body, "delivery_date")
    qty = req_int(body, "quantity_lbs")
    if qty <= 0:
        fail("ERR_INVALID_REQUEST", "quantity_lbs must be > 0")
    # Temporal (priority 7): delivery inside the window, both ends inclusive.
    if delivery_date < rec["delivery_window_start"] or delivery_date > rec["delivery_window_end"]:
        fail("ERR_DELIVERY_OUTSIDE_WINDOW",
             "delivery_date is outside the delivery window")
    # Shape/quantity (priority 9): over-fill, then product quality spec.
    if rec["delivered_lbs"] + qty > rec["quantity_lbs"]:
        fail("ERR_OVER_DELIVERY",
             "delivery would push delivered_lbs above quantity_lbs")
    protein = get_decimal(body, "actual_protein_pct")
    ffa = get_decimal(body, "actual_ffa_pct")
    if rec["product"] == "SOY_MEAL":
        if protein is None:
            fail("ERR_INVALID_REQUEST", "actual_protein_pct is required for SOY_MEAL")
        if protein < rec["min_protein_pct"]:
            fail("ERR_QUALITY_SPEC_FAILED",
                 "protein below min_protein_pct")
    else:
        if ffa is None:
            fail("ERR_INVALID_REQUEST",
                 "actual_ffa_pct is required for SOY_OIL and BIODIESEL_FEEDSTOCK")
        if ffa > rec["max_ffa_pct"]:
            fail("ERR_QUALITY_SPEC_FAILED",
                 "free fatty acids above max_ffa_pct")
    rec["deliveries"].append({
        "delivery_date": delivery_date,
        "quantity_lbs": qty,
        "actual_protein_pct": protein,
        "actual_ffa_pct": ffa,
        "recorded_at": get_clock(),
    })
    rec["delivered_lbs"] += qty
    if rec["delivered_lbs"] == rec["quantity_lbs"]:
        rec["status"] = "FULFILLED"
    else:
        rec["status"] = "DELIVERING"
    touch(rec)
    return success_obj(to_jsonable(rec), 201)
