"""Terminals, brands, arrival allowances, exclusivity grants and products."""
from flask import Blueprint

import clock
import db
import response
from errors import ApiError
from middleware import actor, body, endpoint
from services import mix
from services.lookup import fetch, fetch_body, listing
from services.scope import ALL_ROLES, STAFF_ROLES
from services.validate import (PERIOD_CODE, UPPER2, UPPER3, opt_bool, opt_int, opt_enum,
                               opt_string, present, req_enum, req_int, req_string, req_ts)

bp = Blueprint("estate", __name__)

CATEGORIES = ("LIQUOR", "TOBACCO", "FRAGRANCE", "CONFECTIONERY", "ELECTRONICS")
REGIMES = ("ICAO_STEB", "NONE")
SCOPES = ("TERMINAL_EXCLUSIVE", "CATEGORY_PREFERRED")


# --------------------------------------------------------------------------
# Terminals
# --------------------------------------------------------------------------
@bp.post("/terminals")
@endpoint("TerminalAdmin")
def create_terminal():
    payload = body()
    iata_code = req_string(payload, "iata_code", pattern=UPPER3)
    name = req_string(payload, "name")
    country_code = req_string(payload, "country_code", pattern=UPPER2)
    regime = opt_enum(payload, "sealed_bag_regime", REGIMES, default="ICAO_STEB")
    liquid_limit_ml = opt_int(payload, "liquid_limit_ml", default=1000, minimum=0)
    terminal = db.base()
    terminal.update({
        "iata_code": iata_code,
        "name": name,
        "country_code": country_code,
        "sealed_bag_regime": regime,
        "liquid_limit_ml": liquid_limit_ml,
        "traveler_nationality_mix": {},
        "scanned_itinerary_count_30d": 0,
        "unaccounted_duty_liability_cents": 0,
    })
    db.terminals[terminal["id"]] = terminal
    return response.created(db.public(terminal))


@bp.get("/terminals/<terminal_id>")
@endpoint(*STAFF_ROLES)
def get_terminal(terminal_id):
    return response.single(db.public(fetch("terminals", terminal_id)))


@bp.get("/terminals")
@endpoint(*STAFF_ROLES)
def list_terminals():
    rows, limit, offset, total = listing(db.terminals, ("country_code",))
    return response.collection(rows, limit, offset, total)


@bp.get("/terminals/<terminal_id>/nationality-mix")
@endpoint("TerminalAdmin")
def terminal_nationality_mix(terminal_id):
    terminal = fetch("terminals", terminal_id)
    size, mix_bps = mix.compute(terminal["id"])
    return response.single({
        "window_days": mix.WINDOW_DAYS,
        "scanned_itinerary_count": size,
        "mix_bps": mix_bps,
    })


# --------------------------------------------------------------------------
# Brands
# --------------------------------------------------------------------------
@bp.post("/brands")
@endpoint("TerminalAdmin")
def create_brand():
    payload = body()
    name = req_string(payload, "name")
    category = req_enum(payload, "category", CATEGORIES)
    brand = db.base()
    brand.update({
        "name": name,
        "category": category,
        "status": "ACTIVE",
        "suspended_at": None,
    })
    db.brands[brand["id"]] = brand
    return response.created(db.public(brand))


@bp.get("/brands/<brand_id>")
@endpoint(*STAFF_ROLES)
def get_brand(brand_id):
    return response.single(db.public(fetch("brands", brand_id)))


@bp.get("/brands")
@endpoint(*STAFF_ROLES)
def list_brands():
    rows, limit, offset, total = listing(db.brands, ("category", "status"))
    return response.collection(rows, limit, offset, total)


@bp.post("/brands/<brand_id>/suspend")
@endpoint("TerminalAdmin")
def suspend_brand(brand_id):
    brand = fetch("brands", brand_id)
    if brand["status"] != "ACTIVE":
        raise ApiError("ERR_BRAND_ALREADY_SUSPENDED")
    brand["status"] = "SUSPENDED"
    brand["suspended_at"] = clock.now_iso()
    db.touch(brand)
    for product in db.ordered(db.products,
                              lambda p: p["brand_id"] == brand["id"]
                              and p["assortment_status"] == "LISTED"):
        product["assortment_status"] = "DELISTED"
        product["listed_at"] = None
        db.touch(product)
    return response.single(db.public(brand))


# --------------------------------------------------------------------------
# Arrival-allowance rules
# --------------------------------------------------------------------------
@bp.post("/allowance-rules")
@endpoint("TerminalAdmin")
def create_allowance_rule():
    payload = body()
    destination_country = req_string(payload, "destination_country", pattern=UPPER2)
    category = req_enum(payload, "category", CATEGORIES)
    allowance_units = req_int(payload, "allowance_units", minimum=0)
    advisory_text = req_string(payload, "advisory_text")
    for existing in db.ordered(db.allowance_rules,
                               lambda r: r["status"] == "ACTIVE"
                               and r["destination_country"] == destination_country
                               and r["category"] == category):
        existing["status"] = "SUPERSEDED"
        existing["superseded_at"] = clock.now_iso()
        db.touch(existing)
    rule = db.base()
    rule.update({
        "destination_country": destination_country,
        "category": category,
        "allowance_units": allowance_units,
        "advisory_text": advisory_text,
        "status": "ACTIVE",
        "superseded_at": None,
    })
    db.allowance_rules[rule["id"]] = rule
    return response.created(db.public(rule))


@bp.get("/allowance-rules/<allowance_rule_id>")
@endpoint(*ALL_ROLES)
def get_allowance_rule(allowance_rule_id):
    return response.single(db.public(fetch("allowance_rules", allowance_rule_id)))


@bp.get("/allowance-rules")
@endpoint(*ALL_ROLES)
def list_allowance_rules():
    rows, limit, offset, total = listing(
        db.allowance_rules, ("destination_country", "category", "status"))
    return response.collection(rows, limit, offset, total)


# --------------------------------------------------------------------------
# Exclusivity grants
# --------------------------------------------------------------------------
@bp.post("/exclusivity-grants")
@endpoint("TerminalAdmin")
def create_grant():
    payload = body()
    terminal = fetch_body("terminals", "terminal_id", payload)
    brand = fetch_body("brands", "brand_id", payload)
    category = req_enum(payload, "category", CATEGORIES)
    scope = req_enum(payload, "scope", SCOPES)
    effective_from = req_ts(payload, "effective_from")
    effective_to = req_ts(payload, "effective_to")
    if effective_to <= effective_from:
        raise ApiError("ERR_INVALID_REQUEST", "effective_to must be strictly later than effective_from.")
    for existing in db.ordered(db.grants,
                              lambda g: g["status"] == "ACTIVE"
                              and g["terminal_id"] == terminal["id"]
                              and g["category"] == category):
        stored_from = clock.parse(existing["effective_from"])
        stored_to = clock.parse(existing["effective_to"])
        if stored_from < effective_to and effective_from < stored_to:
            raise ApiError("ERR_EXCLUSIVITY_WINDOW_OVERLAP")
    grant = db.base()
    grant.update({
        "brand_id": brand["id"],
        "terminal_id": terminal["id"],
        "category": category,
        "scope": scope,
        "effective_from": clock.fmt(effective_from),
        "effective_to": clock.fmt(effective_to),
        "status": "ACTIVE",
        "revoked_at": None,
    })
    db.grants[grant["id"]] = grant
    return response.created(db.public(grant))


@bp.get("/exclusivity-grants/<grant_id>")
@endpoint(*STAFF_ROLES)
def get_grant(grant_id):
    return response.single(db.public(fetch("grants", grant_id)))


@bp.get("/exclusivity-grants")
@endpoint(*STAFF_ROLES)
def list_grants():
    rows, limit, offset, total = listing(
        db.grants, ("brand_id", "terminal_id", "category", "scope", "status"))
    return response.collection(rows, limit, offset, total)


@bp.post("/exclusivity-grants/<grant_id>/revoke")
@endpoint("TerminalAdmin")
def revoke_grant(grant_id):
    grant = fetch("grants", grant_id)
    if grant["status"] != "ACTIVE":
        raise ApiError("ERR_GRANT_NOT_ACTIVE")
    grant["status"] = "REVOKED"
    grant["revoked_at"] = clock.now_iso()
    db.touch(grant)
    return response.single(db.public(grant))


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------
@bp.post("/products")
@endpoint("TerminalAdmin")
def create_product():
    payload = body()
    brand = fetch_body("brands", "brand_id", payload)
    sku = req_string(payload, "sku")
    category = req_enum(payload, "category", CATEGORIES)
    unit_price_cents = req_int(payload, "unit_price_cents", minimum=1)
    duty_rate_bps = req_int(payload, "duty_rate_bps", minimum=0, maximum=10000)
    vat_rate_bps = req_int(payload, "vat_rate_bps", minimum=0, maximum=10000)
    target_nationality_code = req_string(payload, "target_nationality_code", pattern=UPPER2)
    is_liquid = opt_bool(payload, "is_liquid", default=False)
    if is_liquid:
        liquid_ml = req_int(payload, "liquid_ml", minimum=1)
    else:
        liquid_ml = None
    required_share = opt_int(payload, "required_nationality_share_bps",
                             default=1500, minimum=0, maximum=10000)
    for existing in db.products.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU")
    if category != brand["category"]:
        raise ApiError("ERR_PRODUCT_CATEGORY_MISMATCH")
    product = db.base()
    product.update({
        "brand_id": brand["id"],
        "sku": sku,
        "category": category,
        "unit_price_cents": unit_price_cents,
        "duty_rate_bps": duty_rate_bps,
        "vat_rate_bps": vat_rate_bps,
        "is_liquid": is_liquid,
        "liquid_ml": liquid_ml,
        "target_nationality_code": target_nationality_code,
        "required_nationality_share_bps": required_share,
        "assortment_status": "PENDING",
        "listed_at": None,
    })
    db.products[product["id"]] = product
    return response.created(db.public(product))


@bp.get("/products/<product_id>")
@endpoint(*ALL_ROLES)
def get_product(product_id):
    return response.single(db.public(fetch("products", product_id)))


@bp.get("/products")
@endpoint(*ALL_ROLES)
def list_products():
    rows, limit, offset, total = listing(
        db.products, ("brand_id", "category", "assortment_status"))
    return response.collection(rows, limit, offset, total)


@bp.post("/products/<product_id>/list")
@endpoint("TerminalAdmin")
def list_product(product_id):
    product = fetch("products", product_id)
    if product["assortment_status"] != "PENDING":
        raise ApiError("ERR_PRODUCT_NOT_PENDING")
    brand = db.brands[product["brand_id"]]
    if brand["status"] != "ACTIVE":
        raise ApiError("ERR_BRAND_SUSPENDED")
    stocking_terminal_ids = []
    for item in db.ordered(db.stock_items, lambda s: s["product_id"] == product["id"]):
        if item["terminal_id"] not in stocking_terminal_ids:
            stocking_terminal_ids.append(item["terminal_id"])
    now = clock.now()
    for terminal_id in stocking_terminal_ids:
        for grant in db.ordered(db.grants,
                                lambda g: g["status"] == "ACTIVE"
                                and g["terminal_id"] == terminal_id
                                and g["scope"] == "TERMINAL_EXCLUSIVE"
                                and g["category"] == product["category"]
                                and g["brand_id"] != product["brand_id"]):
            if clock.parse(grant["effective_from"]) <= now < clock.parse(grant["effective_to"]):
                raise ApiError("ERR_EXCLUSIVITY_CONFLICT")
    for terminal_id in stocking_terminal_ids:
        terminal = db.terminals[terminal_id]
        share = terminal["traveler_nationality_mix"].get(product["target_nationality_code"], 0)
        if share < product["required_nationality_share_bps"]:
            raise ApiError("ERR_NATIONALITY_MIX_BELOW_THRESHOLD")
    product["assortment_status"] = "LISTED"
    product["listed_at"] = clock.now_iso()
    db.touch(product)
    return response.single(db.public(product))
