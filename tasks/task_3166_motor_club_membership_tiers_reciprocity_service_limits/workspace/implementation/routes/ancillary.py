"""Ancillary products and sales."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB, CLOCK, new_id, stamp_new, touch
from errors import (
    not_found, invalid_request, invalid_state, business,
    ERR_PRODUCT_TIER_GATE, ERR_SOD_CONFLICT, ERR_REFUND_WINDOW_EXPIRED,
)
from middleware import require_auth
from response import ok_obj
from routes._common import list_response
from services.calculations import (
    ancillary_commission_cents, tier_by_code, REFUND_WINDOW_DAYS,
)
from services.serialize import public
from services.validate import (
    body_json, req_string, req_int, opt_enum, opt_string,
)

bp = Blueprint("ancillary", __name__)

PRODUCT_TYPES = {"TRAVEL_AGENCY", "INSURANCE_AGENCY", "IDENTITY_PROTECTION"}
TIER_CODES = {"CLASSIC", "PLUS", "PREMIER"}
PRODUCT_READ = {"ClubAdmin", "Agent", "MemberServicesRep"}
SALE_READ = {"Agent", "MemberServicesRep"}


def _get_product(productId):
    p = DB.ancillary_products.get(productId)
    if p is None:
        raise not_found("ancillary product not found")
    return p


def _get_sale(saleId):
    s = DB.ancillary_sales.get(saleId)
    if s is None:
        raise not_found("ancillary sale not found")
    return s


# --------------------------------------------------------------- products ---

@bp.post("/motor-club/ancillary-products")
def create_product():
    require_auth({"ClubAdmin"})
    data = body_json()
    product_type = data.get("product_type")
    if product_type not in PRODUCT_TYPES:
        raise invalid_request("product_type must be TRAVEL_AGENCY, INSURANCE_AGENCY or IDENTITY_PROTECTION")
    name = req_string(data, "name")
    price = req_int(data, "price_cents", min_value=0)
    min_tier = data.get("min_tier_code")
    if min_tier not in TIER_CODES:
        raise invalid_request("min_tier_code must be CLASSIC, PLUS or PREMIER")
    commission_bps = req_int(data, "commission_bps", min_value=0, max_value=5000)
    for p in DB.ancillary_products.values():
        if p["product_type"] == product_type and p["name"] == name:
            raise invalid_request("name must be unique per product_type")
    product = {
        "id": new_id(),
        "product_type": product_type,
        "name": name,
        "price_cents": price,
        "min_tier_code": min_tier,
        "commission_bps": commission_bps,
        "status": "ACTIVE",
    }
    stamp_new(product)
    DB.ancillary_products[product["id"]] = product
    return ok_obj(public(product), 201)


@bp.get("/motor-club/ancillary-products")
def list_products():
    require_auth(PRODUCT_READ)
    pt = request.args.get("product_type")
    status = request.args.get("status")

    def filt(p):
        if pt is not None and p["product_type"] != pt:
            return False
        if status is not None and p["status"] != status:
            return False
        return True

    return list_response(list(DB.ancillary_products.values()), filt)


@bp.get("/motor-club/ancillary-products/<productId>")
def get_product(productId):
    require_auth(PRODUCT_READ)
    return ok_obj(public(_get_product(productId)))


@bp.put("/motor-club/ancillary-products/<productId>")
def update_product(productId):
    require_auth({"ClubAdmin"})
    p = _get_product(productId)
    data = body_json()
    if "name" in data and data["name"] is not None:
        if not isinstance(data["name"], str) or not data["name"]:
            raise invalid_request("name must be a non-empty string")
        for other in DB.ancillary_products.values():
            if (other["id"] != p["id"] and other["product_type"] == p["product_type"]
                    and other["name"] == data["name"]):
                raise invalid_request("name must be unique per product_type")
        p["name"] = data["name"]
    if "price_cents" in data and data["price_cents"] is not None:
        v = data["price_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise invalid_request("price_cents must be an integer >= 0")
        p["price_cents"] = v
    if "min_tier_code" in data and data["min_tier_code"] is not None:
        if data["min_tier_code"] not in TIER_CODES:
            raise invalid_request("min_tier_code must be CLASSIC, PLUS or PREMIER")
        p["min_tier_code"] = data["min_tier_code"]
    if "commission_bps" in data and data["commission_bps"] is not None:
        v = data["commission_bps"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 5000:
            raise invalid_request("commission_bps must be between 0 and 5000")
        p["commission_bps"] = v
    if "status" in data and data["status"] is not None:
        if data["status"] not in {"ACTIVE", "RETIRED"}:
            raise invalid_request("status must be ACTIVE or RETIRED")
        p["status"] = data["status"]
    touch(p)
    return ok_obj(public(p))


# ------------------------------------------------------------------ sales ---

@bp.post("/motor-club/ancillary-sales")
def create_sale():
    user_id, _ = require_auth({"Agent"})
    data = body_json()
    membership_id = req_string(data, "membership_id")
    product_id = req_string(data, "product_id")
    m = DB.memberships.get(membership_id)
    if m is None:
        raise not_found("membership not found")
    p = DB.ancillary_products.get(product_id)
    if p is None:
        raise not_found("product not found")
    # purchase gating (threefold; any failure -> ERR_PRODUCT_TIER_GATE)
    if m["status"] not in {"ACTIVE", "REINSTATED"}:
        raise business(ERR_PRODUCT_TIER_GATE,
                       "membership must be ACTIVE or REINSTATED to purchase")
    if p["status"] != "ACTIVE":
        raise business(ERR_PRODUCT_TIER_GATE, "product is not ACTIVE")
    m_tier = tier_by_code(m["tier_code"])
    min_tier = tier_by_code(p["min_tier_code"])
    if m_tier is None or min_tier is None or m_tier["rank"] < min_tier["rank"]:
        raise business(ERR_PRODUCT_TIER_GATE,
                       "membership tier is below the product minimum tier")
    price = p["price_cents"]
    commission = ancillary_commission_cents(price, p["commission_bps"])
    sale = {
        "id": new_id(),
        "membership_id": m["id"],
        "product_id": p["id"],
        "sold_by_agent_id": user_id,
        "price_cents": price,
        "commission_cents": commission,
        "status": "ACTIVE",
        "_created_dt": CLOCK.now(),
    }
    stamp_new(sale)
    DB.ancillary_sales[sale["id"]] = sale
    m["account_credit_cents"] -= price
    touch(m)
    return ok_obj(public(sale), 201)


@bp.get("/motor-club/ancillary-sales")
def list_sales():
    require_auth(SALE_READ)
    membership_id = request.args.get("membership_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")

    def filt(s):
        if membership_id is not None and s["membership_id"] != membership_id:
            return False
        if product_id is not None and s["product_id"] != product_id:
            return False
        if status is not None and s["status"] != status:
            return False
        return True

    return list_response(list(DB.ancillary_sales.values()), filt)


@bp.get("/motor-club/ancillary-sales/<saleId>")
def get_sale(saleId):
    require_auth(SALE_READ)
    return ok_obj(public(_get_sale(saleId)))


@bp.post("/motor-club/ancillary-sales/<saleId>/refund")
def refund_sale(saleId):
    user_id, role = require_auth({"Agent", "MemberServicesRep"})
    s = _get_sale(saleId)
    if s["status"] != "ACTIVE":
        raise invalid_state("refund is permitted only on an ACTIVE sale")
    # SoD guard runs before the temporal window per PRD 3.9
    if role == "Agent" and user_id != s["sold_by_agent_id"]:
        raise business(ERR_SOD_CONFLICT,
                       "an Agent may refund only their own sales")
    now = CLOCK.now()
    if now > s["_created_dt"] + timedelta(days=REFUND_WINDOW_DAYS):
        raise business(ERR_REFUND_WINDOW_EXPIRED,
                       "refund window (30 days from sale) has expired")
    s["status"] = "REFUNDED"
    touch(s)
    m = DB.memberships.get(s["membership_id"])
    if m is not None:
        m["account_credit_cents"] += s["price_cents"]
        touch(m)
    return ok_obj(public(s))
