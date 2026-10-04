"""Routes: PricingRecommendations."""

from decimal import Decimal

from flask import Blueprint, request

from calc import MAX_OVERRIDE_BAND_PCT
from db import db, new_id, now_iso, get_clock
from errors import (
    invalid_request,
    invalid_state_transition,
    override_band_exceeded,
    pricing_window_overlap,
)
from middleware import get_or_404, parse_iso, req_int, req_iso, req_str, require_roles
from response import body, ok_object, paginate

bp = Blueprint("pricing", __name__)

GET_ROLES = ("PortfolioManager", "RevenueAnalyst", "OwnerRep", "PropertyAccountant")


def pricing_out(p):
    return dict(p)


def _arg(name):
    return request.args.get(name)


@bp.post("/mgmt/properties/<propertyId>/pricing")
def create_pricing(propertyId):
    require_roles("RevenueAnalyst")
    get_or_404(db.properties, propertyId)
    data = body()
    unit_label = req_str(data, "unit_label")
    recommended_rent_cents = req_int(data, "recommended_rent_cents")
    if recommended_rent_cents < 0:
        raise invalid_request("recommended_rent_cents must be non-negative")
    start = req_iso(data, "effective_start_date")
    end = req_iso(data, "effective_end_date")
    now = now_iso()
    p = {
        "id": new_id(),
        "property_id": propertyId,
        "unit_label": unit_label,
        "recommended_rent_cents": recommended_rent_cents,
        "effective_start_date": data["effective_start_date"],
        "effective_end_date": data["effective_end_date"],
        "status": "PROPOSED",
        "final_rent_cents": None,
        "override_rent_cents": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.pricing[p["id"]] = p
    return ok_object(pricing_out(p), status=201)


@bp.get("/mgmt/pricing/<pricingId>")
def get_pricing(pricingId):
    require_roles(*GET_ROLES)
    p = get_or_404(db.pricing, pricingId)
    return ok_object(pricing_out(p))


@bp.get("/mgmt/properties/<propertyId>/pricing")
def list_pricing_for_property(propertyId):
    require_roles(*GET_ROLES)
    get_or_404(db.properties, propertyId)
    unit_label = _arg("unit_label")
    status = _arg("status")
    items = sorted(
        (p for p in db.pricing.values() if p["property_id"] == propertyId),
        key=lambda x: (x["created_at"], x["id"]),
    )
    if unit_label is not None:
        items = [p for p in items if p["unit_label"] == unit_label]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate([pricing_out(p) for p in items])


@bp.get("/mgmt/pricing")
def list_pricing():
    require_roles(*GET_ROLES)
    property_id = _arg("property_id")
    unit_label = _arg("unit_label")
    status = _arg("status")
    items = sorted(db.pricing.values(), key=lambda x: (x["created_at"], x["id"]))
    if property_id is not None:
        items = [p for p in items if p["property_id"] == property_id]
    if unit_label is not None:
        items = [p for p in items if p["unit_label"] == unit_label]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate([pricing_out(p) for p in items])


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap."""
    return a_start < b_end and b_start < a_end


@bp.post("/mgmt/pricing/<pricingId>/publish")
def publish_pricing(pricingId):
    require_roles("RevenueAnalyst")
    p = get_or_404(db.pricing, pricingId)
    if p["status"] != "PROPOSED":
        raise invalid_state_transition("Recommendation must be PROPOSED to publish")
    start = parse_iso(p["effective_start_date"])
    end = parse_iso(p["effective_end_date"])
    if start is None or end is None or not (start < end):
        raise invalid_request("effective_start_date must be strictly before effective_end_date")
    for other in db.pricing.values():
        if (
            other["id"] != p["id"]
            and other["property_id"] == p["property_id"]
            and other["unit_label"] == p["unit_label"]
            and other["status"] == "PUBLISHED"
        ):
            o_start = parse_iso(other["effective_start_date"])
            o_end = parse_iso(other["effective_end_date"])
            if _windows_overlap(start, end, o_start, o_end):
                raise pricing_window_overlap()
    p["status"] = "PUBLISHED"
    p["final_rent_cents"] = p["recommended_rent_cents"]
    p["updated_at"] = now_iso()
    p["version"] += 1
    return ok_object(pricing_out(p))


@bp.post("/mgmt/pricing/<pricingId>/override")
def override_pricing(pricingId):
    require_roles("OwnerRep")
    p = get_or_404(db.pricing, pricingId)
    if p["status"] != "PUBLISHED":
        raise invalid_state_transition("Recommendation must be PUBLISHED to override")
    data = body()
    override_rent = req_int(data, "override_rent_cents")
    if override_rent < 0:
        raise invalid_request("override_rent_cents must be non-negative")
    rec = Decimal(p["recommended_rent_cents"])
    band = rec * MAX_OVERRIDE_BAND_PCT
    diff = abs(Decimal(override_rent) - rec)
    if diff > band:
        raise override_band_exceeded()
    p["status"] = "OWNER_OVERRIDDEN"
    p["override_rent_cents"] = override_rent
    p["final_rent_cents"] = override_rent
    p["updated_at"] = now_iso()
    p["version"] += 1
    return ok_object(pricing_out(p))


@bp.post("/mgmt/pricing/<pricingId>/withdraw")
def withdraw_pricing(pricingId):
    require_roles("RevenueAnalyst")
    p = get_or_404(db.pricing, pricingId)
    if p["status"] == "PROPOSED":
        pass
    elif p["status"] == "PUBLISHED":
        start = parse_iso(p["effective_start_date"])
        if get_clock() >= start:
            raise invalid_state_transition("A live price window cannot be withdrawn")
    else:
        raise invalid_state_transition("Recommendation cannot be withdrawn from its current state")
    p["status"] = "WITHDRAWN"
    p["updated_at"] = now_iso()
    p["version"] += 1
    return ok_object(pricing_out(p))
