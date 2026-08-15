"""Clock, shops, welders, NDT vendors (nested routes)."""

from flask import Blueprint

from db import db
from errors import ApiError, ERR_NOT_FOUND, invalid_request
from helpers import (
    json_body, require_fields, parse_datetime, parse_int, NDT_METHODS,
)
from middleware import require_roles, require_any
from response import success_object, success_list
from serializers import shop_out, welder_out, ndt_vendor_out
from services import (
    stamp_new, make_versioned, mutate, get_shop, get_welder,
    continuity_sweep, derive_posture_open_restricted,
)
from helpers import paginate

bp = Blueprint("shops", __name__)

CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/_clock/set_current_utc", methods=["POST"])
@require_roles("ShopAdmin")
def set_clock(user_id, role):
    body = json_body()
    require_fields(body, ["to_iso8601"])
    target_dt = parse_datetime(body["to_iso8601"], "to_iso8601")
    shop_id = body.get("shop_id")
    if shop_id is not None:
        shop = db.shops.get(shop_id)
        if shop is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Shop not found")
        targets = [shop]
        returned = shop
    else:
        targets = list(db.shops.values())
        if not targets:
            raise ApiError(ERR_NOT_FOUND, 404, "Shop not found")
        targets.sort(key=lambda s: s["_seq"])
        returned = targets[0]
    for shop in targets:
        shop["current_utc"] = target_dt
        mutate(shop)
        # welder-continuity sweep + joint/weldment posture recomputation
        continuity_sweep(shop)
        for wm in db.weldments.values():
            if wm["shop_id"] == shop["id"]:
                derive_posture_open_restricted(wm)
    return success_object(shop_out(returned))


# ---------------------------------------------------------------------------
# Shops
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops", methods=["POST"])
@require_roles("ShopAdmin")
def create_shop(user_id, role):
    body = json_body()
    require_fields(body, ["shop_name", "aws_d1_1_revision"])
    if not isinstance(body["shop_name"], str) or not body["shop_name"].strip():
        raise invalid_request("shop_name must be a non-empty string")
    if not isinstance(body["aws_d1_1_revision"], str):
        raise invalid_request("aws_d1_1_revision must be a string")
    limit = body.get("repair_rate_limit_pct", 5)
    if limit is not None:
        limit = parse_int(limit, "repair_rate_limit_pct")
    else:
        limit = 5
    shop = stamp_new({
        "shop_name": body["shop_name"],
        "aws_d1_1_revision": body["aws_d1_1_revision"],
        "repair_rate_limit_pct": limit,
        "current_utc": parse_datetime(CLOCK_DEFAULT_ISO, "current_utc"),
    })
    make_versioned(shop)
    db.shops[shop["id"]] = shop
    return success_object(shop_out(shop), status=201)


@bp.route("/weld-shop/shops/<shop_id>", methods=["GET"])
@require_any
def get_shop_route(user_id, role, shop_id):
    return success_object(shop_out(get_shop(shop_id)))


# ---------------------------------------------------------------------------
# Welders
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/welders", methods=["POST"])
@require_roles("ShopAdmin")
def create_welder(user_id, role, shop_id):
    shop = get_shop(shop_id)
    body = json_body()
    require_fields(body, ["stencil", "full_name"])
    if not isinstance(body["stencil"], str) or not isinstance(body["full_name"], str):
        raise invalid_request("stencil and full_name must be strings")
    welder = stamp_new({
        "shop_id": shop["id"],
        "stencil": body["stencil"],
        "full_name": body["full_name"],
        "status": "ACTIVE",
    })
    make_versioned(welder)
    db.welders[welder["id"]] = welder
    return success_object(welder_out(welder), status=201)


@bp.route("/weld-shop/shops/<shop_id>/welders", methods=["GET"])
@require_any
def list_welders(user_id, role, shop_id):
    shop = get_shop(shop_id)
    records = [w for w in db.welders.values() if w["shop_id"] == shop["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([welder_out(w) for w in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/welders/<welder_id>", methods=["GET"])
@require_any
def get_welder_route(user_id, role, shop_id, welder_id):
    get_shop(shop_id)
    return success_object(welder_out(get_welder(shop_id, welder_id)))


# ---------------------------------------------------------------------------
# NDT vendors
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/ndt-vendors", methods=["POST"])
@require_roles("ShopAdmin")
def create_ndt_vendor(user_id, role, shop_id):
    shop = get_shop(shop_id)
    body = json_body()
    require_fields(body, ["vendor_name", "supported_methods", "hourly_capacity"])
    if not isinstance(body["vendor_name"], str):
        raise invalid_request("vendor_name must be a string")
    methods = body["supported_methods"]
    if not isinstance(methods, list) or any(m not in NDT_METHODS for m in methods):
        raise invalid_request("supported_methods must be a subset of [VT, UT, RT]")
    capacity = parse_int(body["hourly_capacity"], "hourly_capacity")
    vendor = stamp_new({
        "shop_id": shop["id"],
        "vendor_name": body["vendor_name"],
        "supported_methods": list(methods),
        "hourly_capacity": capacity,
        "status": "ACTIVE",
    })
    make_versioned(vendor)
    db.ndt_vendors[vendor["id"]] = vendor
    return success_object(ndt_vendor_out(vendor), status=201)


@bp.route("/weld-shop/shops/<shop_id>/ndt-vendors", methods=["GET"])
@require_any
def list_ndt_vendors(user_id, role, shop_id):
    shop = get_shop(shop_id)
    records = [v for v in db.ndt_vendors.values() if v["shop_id"] == shop["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([ndt_vendor_out(v) for v in page], limit, offset, total)
