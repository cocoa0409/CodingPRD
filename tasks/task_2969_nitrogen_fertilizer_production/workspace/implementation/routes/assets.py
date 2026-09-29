"""Storage assets and the seasonal set-aside (PRD 3.6)."""
from flask import Blueprint, request

import serialize
import validate as v
from auth import ALL_ROLES, LOGISTICS_COORDINATOR, actor
from envelope import list_response, object_response, paging
from guards import duplicate, filtered, load, state
from mutate import touch
from store import db, stamp_new
from util import D

bp = Blueprint("assets", __name__)
PREFIX = "/nitrogen-ops/storage-assets"
ASSET_KINDS = ("DOME", "TANK", "TERMINAL")
SECURITY_CLASSES = ("BASIC", "CONTROLLED", "HIGH_SECURITY")
PRODUCT_CODES = ("ANHYDROUS_AMMONIA", "AMMONIUM_NITRATE", "UAN_SOLUTION", "UREA")


@bp.post(PREFIX)
def create_asset():
    actor([LOGISTICS_COORDINATOR])
    body = v.get_body()
    plant_id = v.s_id(body, "plant_id")
    asset_code = v.s_code(body, "asset_code", 2, 16)
    asset_kind = v.s_enum(body, "asset_kind", ASSET_KINDS)
    product_code = v.s_enum(body, "product_code", PRODUCT_CODES)
    capacity = v.s_num(body, "capacity_tons", 3, gt=0)
    security_class = v.s_enum(body, "security_class", SECURITY_CLASSES)
    seasonal = v.s_num(body, "seasonal_reserve_pct", 2, required=False,
                       default=D("0.00"), ge=0, le=1)
    load("plants", plant_id)
    duplicate("assets", "asset_code", asset_code, scope=("plant_id", plant_id))
    row = {
        "plant_id": plant_id,
        "asset_code": asset_code,
        "asset_kind": asset_kind,
        "product_code": product_code,
        "capacity_tons": capacity,
        "security_class": security_class,
        "seasonal_reserve_pct": seasonal,
        "opening_balance_tons": D("0.000"),
    }
    stamp_new(row)
    db.assets[row["id"]] = row
    return object_response(serialize.asset_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_asset(id):
    actor(ALL_ROLES)
    return object_response(serialize.asset_json(load("assets", id)))


@bp.get(PREFIX)
def list_assets():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("assets", [
        ("plant_id", v.query_str("plant_id")),
        ("asset_kind", v.query_enum("asset_kind", ASSET_KINDS)),
        ("product_code", v.query_enum("product_code", PRODUCT_CODES)),
    ])
    return list_response(serialize.dump("assets", rows), limit, offset)


@bp.post(PREFIX + "/<id>/opening-balance")
def opening_balance(id):
    """A physically counted starting position, in place of fabricated history."""
    actor([LOGISTICS_COORDINATOR])
    body = v.get_body()
    tons = v.s_num(body, "opening_balance_tons", 3, ge=0)
    asset = load("assets", id)
    state(tons <= asset["capacity_tons"], "ERR_STORAGE_CAPACITY_EXCEEDED")
    asset["opening_balance_tons"] = tons
    touch(asset)
    return object_response(serialize.asset_json(asset))
