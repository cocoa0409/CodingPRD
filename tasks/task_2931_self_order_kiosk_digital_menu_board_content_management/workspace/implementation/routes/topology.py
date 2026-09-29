"""Price zones, store clusters and stores (PRD 3.1)."""
from flask import Blueprint

import auth
import calc
import constants as C
import derive
import logical_clock as clockmod
import response
import serialize
import shapes
from db import DB, new_row
from errors import fail
from routes.common import fk, listing, path_row, unique_or_conflict

bp = Blueprint("topology", __name__)

READ_ROLES = auth.ALL_READ_ROLES


@bp.post("/price-zones")
def create_price_zone():
    auth.enter(["PlatformAdmin"])
    data = shapes.body()
    zone_code = shapes.req_str(data, "zone_code", 1, 16)
    currency = shapes.opt_str(data, "currency_code", 3, 3, "USD")
    if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
        fail("ERR_INVALID_REQUEST", "currency_code must be exactly 3 uppercase letters")
    multiplier = shapes.req_int(data, "price_multiplier_bp", 5000, 20000)
    rounding = shapes.opt_enum(data, "psychological_rounding", C.ROUNDING_STYLES, "NONE")
    tax = shapes.req_int(data, "tax_rate_bp", 0, 2500)
    cap = shapes.req_int(data, "max_uplift_bp", 0, 10000)
    unique_or_conflict("price_zones", "zone_code", zone_code)
    row = new_row({
        "zone_code": zone_code,
        "currency_code": currency,
        "price_multiplier_bp": multiplier,
        "psychological_rounding": rounding,
        "tax_rate_bp": tax,
        "max_uplift_bp": cap,
    })
    DB.price_zones[row["id"]] = row
    return response.created(serialize.dump("price_zone", row))


@bp.get("/price-zones")
def list_price_zones():
    auth.enter(READ_ROLES)
    return listing("price_zones", "price_zone")


@bp.get("/price-zones/<price_zone_id>")
def get_price_zone(price_zone_id):
    auth.enter(READ_ROLES)
    row = path_row("price_zones", price_zone_id)
    return response.ok(serialize.dump("price_zone", row))


@bp.post("/store-clusters")
def create_cluster():
    auth.enter(["PlatformAdmin", "ContentManager"])
    data = shapes.body()
    parent_id = fk(data, "parent_cluster_id", "clusters")
    cluster_code = shapes.req_str(data, "cluster_code", 1, 24)
    tier = shapes.req_enum(data, "tier", C.CLUSTER_TIERS)
    unique_or_conflict("clusters", "cluster_code", cluster_code)
    if parent_id is not None:
        if len(calc.cluster_chain_ids(parent_id)) + 1 > C.MAX_CLUSTER_CHAIN_DEPTH:
            fail("ERR_CLUSTER_CHAIN_INVALID", "the resulting chain exceeds five clusters")
    row = new_row({
        "cluster_code": cluster_code,
        "tier": tier,
        "parent_cluster_id": parent_id,
        "chain_depth": 1,
        "published_bundle_version": 0,
    })
    DB.clusters[row["id"]] = row
    derive.recompute_cluster(row, bump=False)
    return response.created(serialize.dump("cluster", row))


@bp.get("/store-clusters")
def list_clusters():
    auth.enter(READ_ROLES)
    return listing("clusters", "cluster")


@bp.get("/store-clusters/<cluster_id>")
def get_cluster(cluster_id):
    auth.enter(READ_ROLES)
    row = path_row("clusters", cluster_id)
    derive.recompute_cluster(row)
    return response.ok(serialize.dump("cluster", row))


@bp.post("/stores")
def create_store():
    auth.enter(["PlatformAdmin"])
    data = shapes.body()
    cluster_id = fk(data, "cluster_id", "clusters")
    zone_id = fk(data, "price_zone_id", "price_zones")
    store_code = shapes.req_str(data, "store_code", 1, 12)
    if cluster_id is None:
        shapes.req_str(data, "cluster_id", 1, None)
    if zone_id is None:
        shapes.req_str(data, "price_zone_id", 1, None)
    offset = shapes.req_int(data, "timezone_offset_minutes", -720, 840)
    certified = shapes.req_instant(data, "accessibility_certified_until_utc")
    unique_or_conflict("stores", "store_code", store_code)
    row = new_row({
        "store_code": store_code,
        "cluster_id": cluster_id,
        "price_zone_id": zone_id,
        "timezone_offset_minutes": offset,
        "accessibility_certified_until_utc": clockmod.iso(certified),
        "daily_order_seq_counter": 0,
        "seq_counter_date": None,
        "open_order_count": 0,
        "content_posture": "OPEN",
    })
    DB.stores[row["id"]] = row
    derive.recompute_store(row, bump=False, audit=False)
    return response.created(serialize.dump("store", row))


@bp.get("/stores")
def list_stores():
    auth.enter(READ_ROLES)
    return listing("stores", "store")


@bp.get("/stores/<store_id>")
def get_store(store_id):
    ctx = auth.enter(READ_ROLES)
    auth.require_store_scope(ctx, store_id)
    row = path_row("stores", store_id)
    derive.recompute_store(row)
    return response.ok(serialize.dump("store", row))
