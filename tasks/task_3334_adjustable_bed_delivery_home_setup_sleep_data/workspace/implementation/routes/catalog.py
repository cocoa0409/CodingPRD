"""Stores, product models, customers, fit assessments."""
from flask import Blueprint

import calculations as calc
from db import DB
from errors import err_validation, not_found
from helpers import (
    body, new_entity, page, parse_pagination, public, req_field, opt_field,
    require_enum, require_int, require_str, require_bool, sorted_items, touch,
)
from middleware import authenticate, check_customer_ownership, require_roles
from response import success_list, success_object

bp = Blueprint("catalog", __name__)

PRODUCT_CATEGORIES = {"MATTRESS", "ADJUSTABLE_BASE", "AIR_CHAMBER", "PUMP", "ELECTRONICS", "BEDDING"}
TIERS = {"FREE", "PLUS", "PREMIUM"}
SLEEP_POSITIONS = {"SIDE", "BACK", "STOMACH", "COMBINATION"}
WEIGHT_BANDS = {"UNDER_130", "BAND_130_230", "OVER_230"}
FEELS = {"PLUSH", "MEDIUM", "FIRM"}


# ---------------------------------------------------------------- stores
@bp.post("/sleep/stores")
def create_store():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin"})
    data = body()
    name = require_str(req_field(data, "name"), "name")
    zone_codes = req_field(data, "zone_codes")
    if not isinstance(zone_codes, list) or not all(isinstance(z, str) for z in zone_codes):
        raise err_validation("zone_codes must be an array of strings")
    capacity = opt_field(data, "default_window_capacity_slots", 4)
    capacity = require_int(capacity, "default_window_capacity_slots")
    ent = new_entity({
        "name": name,
        "zone_codes": zone_codes,
        "default_window_capacity_slots": capacity,
    })
    DB.stores[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/sleep/stores/<store_id>")
def get_store(store_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "SalesAssociate", "ServiceAgent"})
    ent = DB.stores.get(store_id)
    if ent is None:
        raise not_found("ERR_STORE_NOT_FOUND", "store id does not resolve")
    return success_object(public(ent))


# ---------------------------------------------------------------- product models
@bp.post("/sleep/product-models")
def create_product_model():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin"})
    data = body()
    sku = require_str(req_field(data, "sku"), "sku")
    name = require_str(req_field(data, "name"), "name")
    category = require_enum(req_field(data, "category"), "category", PRODUCT_CATEGORIES)
    price = require_int(req_field(data, "price_cents"), "price_cents")
    repl = require_int(opt_field(data, "replacement_part_price_cents", 0), "replacement_part_price_cents")
    warranty = require_int(req_field(data, "warranty_months"), "warranty_months")
    ent = new_entity({
        "sku": sku,
        "name": name,
        "category": category,
        "price_cents": price,
        "replacement_part_price_cents": repl,
        "warranty_months": warranty,
    })
    DB.product_models[ent["id"]] = ent
    return success_object(public(ent), 201)


# ---------------------------------------------------------------- customers
@bp.post("/sleep/customers")
def create_customer():
    role, uid = authenticate()
    require_roles(role, uid, {"Anonymous"})
    data = body()
    home_store_id = require_str(req_field(data, "home_store_id"), "home_store_id")
    email = require_str(req_field(data, "email"), "email")
    full_name = require_str(req_field(data, "full_name"), "full_name")
    if home_store_id not in DB.stores:
        raise not_found("ERR_STORE_NOT_FOUND", "store id does not resolve")
    ent = new_entity({
        "home_store_id": home_store_id,
        "email": email,
        "full_name": full_name,
        "subscription_tier": "FREE",
        "subscription_status": "ACTIVE",
        "store_credit_cents": 0,
    })
    ent["entitlements"] = calc.entitlements_for_tier("FREE")
    DB.customers[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/sleep/customers/<customer_id>")
def get_customer(customer_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "SalesAssociate", "ServiceAgent", "Customer"})
    ent = DB.customers.get(customer_id)
    if ent is None:
        raise not_found("ERR_CUSTOMER_NOT_FOUND", "customer id does not resolve")
    check_customer_ownership(role, uid, ent["id"])
    return success_object(public(ent))


@bp.get("/sleep/customers")
def list_customers():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "SalesAssociate", "ServiceAgent"})
    limit, offset = parse_pagination()
    items = list(DB.customers.values())
    home_store_id = __import__("flask").request.args.get("home_store_id")
    if home_store_id is not None:
        items = [c for c in items if c["home_store_id"] == home_store_id]
    items = sorted_items(items)
    total = len(items)
    return success_list([public(c) for c in page(items, limit, offset)], limit, offset, total)


@bp.patch("/sleep/customers/<customer_id>/subscription")
def patch_subscription(customer_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin"})
    ent = DB.customers.get(customer_id)
    if ent is None:
        raise not_found("ERR_CUSTOMER_NOT_FOUND", "customer id does not resolve")
    data = body()
    tier = require_enum(req_field(data, "subscription_tier"), "subscription_tier", TIERS)
    ent["subscription_tier"] = tier
    ent["entitlements"] = calc.entitlements_for_tier(tier)
    touch(ent)
    return success_object(public(ent))


# ---------------------------------------------------------------- fit assessments
@bp.post("/sleep/fit-assessments")
def create_fit_assessment():
    role, uid = authenticate()
    require_roles(role, uid, {"SalesAssociate"})
    data = body()
    customer_id = require_str(req_field(data, "customer_id"), "customer_id")
    store_id = require_str(req_field(data, "store_id"), "store_id")
    sleep_position = require_enum(req_field(data, "sleep_position"), "sleep_position", SLEEP_POSITIONS)
    weight_band = require_enum(req_field(data, "weight_band"), "weight_band", WEIGHT_BANDS)
    partner_sleeper = require_bool(req_field(data, "partner_sleeper"), "partner_sleeper")
    preferred_feel = require_enum(req_field(data, "preferred_feel"), "preferred_feel", FEELS)
    supersedes = data.get("supersedes_assessment_id")
    if supersedes is not None and not isinstance(supersedes, str):
        raise err_validation("supersedes_assessment_id must be a string")
    if customer_id not in DB.customers:
        raise not_found("ERR_CUSTOMER_NOT_FOUND", "customer id does not resolve")
    if store_id not in DB.stores:
        raise not_found("ERR_STORE_NOT_FOUND", "store id does not resolve")
    if supersedes is not None and supersedes not in DB.fit_assessments:
        raise not_found("ERR_FIT_ASSESSMENT_NOT_FOUND", "fit assessment id does not resolve")
    ent = new_entity({
        "customer_id": customer_id,
        "store_id": store_id,
        "sleep_position": sleep_position,
        "weight_band": weight_band,
        "partner_sleeper": partner_sleeper,
        "preferred_feel": preferred_feel,
        "recommended_firmness": None,
        "recommended_skus": None,
        "supersedes_assessment_id": supersedes,
        "status": "DRAFT",
        "completed_at": None,
    })
    DB.fit_assessments[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/sleep/fit-assessments/<assessment_id>")
def get_fit_assessment(assessment_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "SalesAssociate", "Customer"})
    ent = DB.fit_assessments.get(assessment_id)
    if ent is None:
        raise not_found("ERR_FIT_ASSESSMENT_NOT_FOUND", "fit assessment id does not resolve")
    check_customer_ownership(role, uid, ent["customer_id"])
    return success_object(public(ent))


@bp.get("/sleep/fit-assessments")
def list_fit_assessments():
    from flask import request
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "SalesAssociate"})
    limit, offset = parse_pagination()
    items = list(DB.fit_assessments.values())
    for key in ("customer_id", "store_id", "supersedes_assessment_id"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if a.get(key) == v]
    items = sorted_items(items)
    total = len(items)
    return success_list([public(a) for a in page(items, limit, offset)], limit, offset, total)


@bp.post("/sleep/fit-assessments/<assessment_id>/complete")
def complete_fit_assessment(assessment_id):
    role, uid = authenticate()
    require_roles(role, uid, {"SalesAssociate"})
    ent = DB.fit_assessments.get(assessment_id)
    if ent is None:
        raise not_found("ERR_FIT_ASSESSMENT_NOT_FOUND", "fit assessment id does not resolve")
    if ent["status"] != "DRAFT":
        from errors import ApiError
        raise ApiError("ERR_INVALID_STATE", 409, "assessment is not DRAFT")
    ent["recommended_firmness"] = calc.recommended_firmness(
        ent["sleep_position"], ent["weight_band"], ent["partner_sleeper"], ent["preferred_feel"]
    )
    ent["recommended_skus"] = calc.recommended_skus(list(DB.product_models.values()))
    ent["completed_at"] = DB.clock.now_iso()
    ent["status"] = "COMPLETED"
    touch(ent)
    supersedes = ent.get("supersedes_assessment_id")
    if supersedes:
        pred = DB.fit_assessments.get(supersedes)
        if pred is not None and pred["status"] == "COMPLETED":
            pred["status"] = "SUPERSEDED"
            touch(pred)
    return success_object(public(ent))
