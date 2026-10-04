"""Catalog resources: logical clock, reps, stores, products."""

from flask import Blueprint

import db as store
import services as svc
from errors import (
    ERR_INVALID_STATE,
    ERR_ROUTE_NOT_ACTIVE,
    ERR_STORE_NOT_ACTIVE,
    ERR_VALIDATION,
    err,
)
from helpers import (
    auth,
    body,
    find_by,
    get,
    new_record,
    opt_enum,
    opt_field,
    opt_int,
    req_enum,
    req_field,
    req_int,
    req_str,
    require_role,
    touch,
)
from response import success

bp = Blueprint("catalog", __name__)

ALL_ROLES = ("PlatformAdmin", "RouteSupervisor", "RouteSalesRep", "StoreManager")


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.post("/dsd/_clock/set_current_utc")
def set_clock():
    uid, role = auth()
    require_role(role, "PlatformAdmin")
    data = body()
    current_utc = req_field(data, "current_utc")
    try:
        store.clock.advance(current_utc)
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, "current_utc must be an ISO 8601 datetime")
    svc.expire_agreements()
    return success({"current_utc": store.clock.iso()}, 200)


# ---------------------------------------------------------------------------
# reps
# ---------------------------------------------------------------------------

@bp.post("/dsd/reps")
def create_rep():
    uid, role = auth()
    require_role(role, "PlatformAdmin")
    data = body()
    rec = new_record()
    rec["full_name"] = req_str(data, "full_name")
    rec["home_depot"] = req_str(data, "home_depot")
    rec["status"] = opt_enum(data, "status", ("ACTIVE", "INACTIVE"), "ACTIVE")
    store.db["reps"][rec["id"]] = rec
    return success(rec, 201)


@bp.get("/dsd/reps/<repId>")
def get_rep(repId):
    auth()
    return success(get("reps", repId), 200)


# ---------------------------------------------------------------------------
# stores
# ---------------------------------------------------------------------------

@bp.post("/dsd/stores")
def create_store():
    uid, role = auth()
    require_role(role, "PlatformAdmin")
    data = body()
    store_code = req_str(data, "store_code")
    name = req_str(data, "name")
    fmt = req_enum(data, "format", ("CONVENIENCE", "GROCERY", "SUPERCENTER", "DOLLAR"))
    policy = req_enum(data, "credit_policy", ("FULL_RETAIL", "SALVAGE_RATE"))
    win_start = req_int(data, "delivery_window_start_minute")
    win_end = req_int(data, "delivery_window_end_minute")
    cap = req_int(data, "store_credit_cap_cents")
    if not (0 <= win_start <= 1439):
        raise err(ERR_VALIDATION, "delivery_window_start_minute out of range")
    if not (1 <= win_end <= 1440):
        raise err(ERR_VALIDATION, "delivery_window_end_minute out of range")
    if win_end <= win_start:
        raise err(ERR_VALIDATION, "delivery_window_end_minute must be > start")
    if cap < 0:
        raise err(ERR_VALIDATION, "store_credit_cap_cents must be >= 0")
    if find_by("stores", "store_code", store_code):
        raise err(ERR_VALIDATION, "store_code must be unique")
    rec = new_record()
    rec.update(
        store_code=store_code,
        name=name,
        format=fmt,
        credit_policy=policy,
        delivery_window_start_minute=win_start,
        delivery_window_end_minute=win_end,
        store_credit_cap_cents=cap,
        promo_rebate_balance_cents=0,
        status="ACTIVE",
    )
    store.db["stores"][rec["id"]] = rec
    return success(rec, 201)


@bp.get("/dsd/stores/<storeId>")
def get_store(storeId):
    auth()
    return success(get("stores", storeId), 200)


@bp.post("/dsd/stores/<storeId>/suspend")
def suspend_store(storeId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("stores", storeId)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Store is not ACTIVE")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(rec, 200)


@bp.post("/dsd/stores/<storeId>/reactivate")
def reactivate_store(storeId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("stores", storeId)
    if rec["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Store is not SUSPENDED")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(rec, 200)


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------

@bp.post("/dsd/products")
def create_product():
    uid, role = auth()
    require_role(role, "PlatformAdmin")
    data = body()
    sku = req_str(data, "sku")
    name = req_str(data, "name")
    price = req_int(data, "case_price_cents")
    shelf_life = req_int(data, "shelf_life_days")
    promo_eligible = opt_field(data, "promo_eligible", True)
    if not isinstance(promo_eligible, bool):
        raise err(ERR_VALIDATION, "promo_eligible must be a boolean")
    if price <= 0:
        raise err(ERR_VALIDATION, "case_price_cents must be > 0")
    if shelf_life <= 0:
        raise err(ERR_VALIDATION, "shelf_life_days must be > 0")
    if find_by("products", "sku", sku):
        raise err(ERR_VALIDATION, "sku must be unique")
    rec = new_record()
    rec.update(
        sku=sku,
        name=name,
        case_price_cents=price,
        shelf_life_days=shelf_life,
        promo_eligible=promo_eligible,
    )
    store.db["products"][rec["id"]] = rec
    return success(rec, 201)


@bp.get("/dsd/products/<productId>")
def get_product(productId):
    auth()
    return success(get("products", productId), 200)
