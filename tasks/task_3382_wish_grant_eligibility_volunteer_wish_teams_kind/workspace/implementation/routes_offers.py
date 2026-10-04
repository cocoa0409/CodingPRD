"""DonationOffer registration (with unit-level FMV) and reads."""

from flask import Blueprint

from auth import require_roles
from db import STORE, new_entity
from errors import ApiError
from resp import ok, created, list_resp
from serialize import ser_offer, ser_line
from util import (
    body_json, req_str, req_int, opt_int, req_enum, req_date,
    rhu_pct, pagination, paginate, bad,
)

bp = Blueprint("offers", __name__)

_CATEGORIES = {"AIRLINE", "RESORT", "RETAILER", "SPONSOR"}
_VALUATIONS = {"RETAIL_BASIS", "PARTNER_DECLARED"}
PARTNER_DECLARED_CAP_PCT = 80


@bp.post("/wish-grant/donation-offers")
@require_roles("InKindOfficer")
def create_offer():
    body = body_json()
    partner_name = req_str(body, "partner_name")
    category = req_enum(body, "category", _CATEGORIES)
    valuation_method = req_enum(body, "valuation_method", _VALUATIONS)
    description = req_str(body, "description")
    quantity_total = req_int(body, "quantity_total")
    if quantity_total < 1:
        bad("quantity_total must be >= 1")
    unit_retail_cents = req_int(body, "unit_retail_cents")
    if unit_retail_cents < 1:
        bad("unit_retail_cents must be >= 1")
    partner_declared = opt_int(body, "partner_declared_unit_cents")
    if valuation_method == "PARTNER_DECLARED":
        if partner_declared is None:
            bad("partner_declared_unit_cents is required for PARTNER_DECLARED")
        if partner_declared < 1:
            bad("partner_declared_unit_cents must be >= 1")
    elif partner_declared is not None and partner_declared < 1:
        bad("partner_declared_unit_cents must be >= 1")
    valid_from = req_date(body, "valid_from")
    valid_until = req_date(body, "valid_until")
    if valid_until < valid_from:
        bad("valid_until must be >= valid_from")

    if valuation_method == "RETAIL_BASIS":
        fmv = unit_retail_cents
    else:
        cap = rhu_pct(unit_retail_cents, PARTNER_DECLARED_CAP_PCT)
        fmv = min(partner_declared, cap)

    o = new_entity(
        partner_name=partner_name,
        category=category,
        valuation_method=valuation_method,
        description=description,
        quantity_total=quantity_total,
        quantity_reserved=0,
        unit_retail_cents=unit_retail_cents,
        partner_declared_unit_cents=partner_declared,
        fmv_unit_cents=fmv,
        valid_from=valid_from,
        valid_until=valid_until,
        status="AVAILABLE",
    )
    STORE["offers"][o["id"]] = o
    return created(ser_offer(o))


@bp.get("/wish-grant/donation-offers/<oid>")
@require_roles("InKindOfficer", "WishCoordinator", "ChapterDirector")
def get_offer(oid):
    o = STORE["offers"].get(oid)
    if o is None:
        raise ApiError("ERR_NOT_FOUND", 404, "DonationOffer not found")
    return ok(ser_offer(o))


@bp.get("/wish-grant/donation-offers/<oid>/line-items")
@require_roles("InKindOfficer", "WishCoordinator", "ChapterDirector")
def list_offer_line_items(oid):
    o = STORE["offers"].get(oid)
    if o is None:
        raise ApiError("ERR_NOT_FOUND", 404, "DonationOffer not found")
    limit, offset = pagination()
    items = sorted(STORE["lines"].values(), key=lambda e: e["created_at"])
    items = [l for l in items if l["donation_offer_id"] == oid]
    page, total, has_more = paginate(items, limit, offset)
    return list_resp([ser_line(l) for l in page], total, limit, offset, has_more)
