"""Pod varieties: create, read, list, transition (incl. CONVERT_RECYCLABLE)."""
from flask import Blueprint, request

from store import db
from helpers import (
    ApiError, body, created, find, init_common, list_ok, ok, touch,
    require_roles, v_enum, v_int, v_str,
)
from serializers import variety_out

bp = Blueprint("varieties", __name__)

ROASTS = ("LIGHT", "MEDIUM", "DARK")
FLAVORS = ("UNFLAVORED", "FLAVORED")
MATERIALS = ("CONVENTIONAL", "RECYCLABLE")
VARIETY_TARGETS = ("PHASE_OUT", "ACTIVE", "DELISTED", "CONVERT_RECYCLABLE")

_DECLARED = {
    ("ACTIVE", "PHASE_OUT"), ("PHASE_OUT", "ACTIVE"),
    ("ACTIVE", "DELISTED"), ("PHASE_OUT", "DELISTED"),
}


def _delist_cascade(variety):
    for r in db["runs"].values():
        if r["variety_id"] == variety["id"] and r["status"] == "RESERVED":
            r["status"] = "CANCELLED"
            touch(r)


@bp.post("/pod-varieties")
@require_roles("BrandManager")
def create_variety():
    b = body()
    raw_brand = b.get("brand_id")
    if not isinstance(raw_brand, str) or raw_brand != request.user_id:
        raise ApiError("ERR_BRAND_OWNERSHIP", 403,
                       "BrandManager may only create varieties for their own brand")
    brand = db["brands"].get(raw_brand)
    if brand is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Brand not found: %s" % raw_brand)
    variety = init_common({
        "brand_id": raw_brand,
        "name": v_str(b, "name"),
        "roast_level": v_enum(b, "roast_level", ROASTS),
        "flavor_family": v_enum(b, "flavor_family", FLAVORS),
        "material": v_enum(b, "material", MATERIALS, required=False) or "CONVENTIONAL",
        "wholesale_price_cents": v_int(b, "wholesale_price_cents"),
        "margin_cents": v_int(b, "margin_cents"),
        "education_notices_sent": 0,
        "status": "ACTIVE",
    })
    db["varieties"][variety["id"]] = variety
    return created(variety_out(variety))


@bp.get("/pod-varieties/<rid>")
@require_roles("BrandManager", "CategoryManager", "ProductionPlanner", "PlatformAdmin")
def get_variety(rid):
    return ok(variety_out(find("varieties", rid)))


@bp.get("/pod-varieties")
@require_roles("BrandManager", "CategoryManager", "ProductionPlanner", "PlatformAdmin")
def list_varieties():
    items = list(db["varieties"].values())
    f_brand = request.args.get("brand_id")
    f_status = request.args.get("status")
    f_roast = request.args.get("roast_level")
    f_material = request.args.get("material")
    if f_brand is not None:
        items = [v for v in items if v["brand_id"] == f_brand]
    if f_status is not None:
        items = [v for v in items if v["status"] == f_status]
    if f_roast is not None:
        items = [v for v in items if v["roast_level"] == f_roast]
    if f_material is not None:
        items = [v for v in items if v["material"] == f_material]
    items.sort(key=lambda v: (v["created_at"], v["_seq"]))
    return list_ok(items, variety_out)


@bp.post("/pod-varieties/<rid>/transition")
@require_roles("BrandManager")
def transition_variety(rid):
    variety = find("varieties", rid)
    if variety["brand_id"] != request.user_id:
        raise ApiError("ERR_BRAND_OWNERSHIP", 403,
                       "BrandManager may only transition varieties of their own brand")
    b = body()
    target = v_enum(b, "target_state", VARIETY_TARGETS)
    if target == "CONVERT_RECYCLABLE":
        edu = v_int(b, "education_notices_sent")
        if variety["status"] != "ACTIVE" or variety["material"] == "RECYCLABLE":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "CONVERT_RECYCLABLE requires an ACTIVE, non-RECYCLABLE variety")
        if not any(l["material_capability"] in ("RECYCLABLE", "BOTH")
                   for l in db["lines"].values()):
            raise ApiError("ERR_NO_COMPATIBLE_LINE", 409,
                           "No filling line can run RECYCLABLE material")
        if edu < 1:
            raise ApiError("ERR_EDUCATION_REQUIRED", 422,
                           "Conversion requires at least 1 education notice")
        variety["material"] = "RECYCLABLE"
        variety["education_notices_sent"] = edu
        touch(variety)
        return ok(variety_out(variety))
    if (variety["status"], target) not in _DECLARED:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "No declared transition from %s to %s" % (variety["status"], target))
    variety["status"] = target
    touch(variety)
    if target == "DELISTED":
        _delist_cascade(variety)
    return ok(variety_out(variety))
