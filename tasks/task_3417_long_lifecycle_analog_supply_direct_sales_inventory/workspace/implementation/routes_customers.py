# Customer routes (PRD 3.2).
from flask import Blueprint

import constants as C
from auth import require_customer_owns, require_roles
from envelope import success
from lookups import get_customer
from serialize import customer_public
from store import store
from validate import (
    as_enum,
    as_int_at_least,
    as_number,
    as_str,
    bad,
    check_unknown_fields,
    get_body,
    require_fields,
)

bp = Blueprint("customers", __name__)

_CREATE_ALLOWED = {"name", "tier", "channel", "credit_limit_cents", "discount_pct"}
_PATCH_ALLOWED = {"tier", "channel", "credit_limit_cents", "discount_pct"}


def _check_discount(value):
    value = as_number(value, "discount_pct")
    if value < 0 or value > 1:
        bad("discount_pct must be a fraction in [0, 1]")
    return value


@bp.post("/customers")
def create_customer():
    require_roles("ChannelManager")
    body = get_body(required=True)
    require_fields(body, ["name", "tier", "channel", "credit_limit_cents"])
    check_unknown_fields(body, _CREATE_ALLOWED)
    name = as_str(body["name"], "name")
    tier = as_enum(body["tier"], "tier", C.CUSTOMER_TIERS)
    channel = as_enum(body["channel"], "channel", C.CHANNELS)
    credit_limit = as_int_at_least(body["credit_limit_cents"], "credit_limit_cents", 0)
    discount_pct = 0
    if "discount_pct" in body:
        discount_pct = _check_discount(body["discount_pct"])
    customer = {
        "name": name,
        "tier": tier,
        "channel": channel,
        "credit_limit_cents": credit_limit,
        "discount_pct": discount_pct,
    }
    customer.update(store.stamp())
    store.customers[customer["id"]] = customer
    return success(customer_public(customer), 201)


@bp.get("/customers/<customer_id>")
def fetch_customer(customer_id):
    uid, role = require_roles("PlatformAdmin", "ChannelManager", "SupplyPlanner", "Customer")
    # Customer role may only fetch its own record (row 2 precedes existence).
    require_customer_owns(customer_id, uid, role)
    return success(customer_public(get_customer(customer_id)))


@bp.patch("/customers/<customer_id>")
def patch_customer(customer_id):
    require_roles("ChannelManager")
    customer = get_customer(customer_id)
    body = get_body(required=True)
    check_unknown_fields(body, _PATCH_ALLOWED)
    new_tier = customer["tier"]
    new_channel = customer["channel"]
    new_credit = customer["credit_limit_cents"]
    new_discount = customer["discount_pct"]
    if "tier" in body:
        new_tier = as_enum(body["tier"], "tier", C.CUSTOMER_TIERS)
    if "channel" in body:
        new_channel = as_enum(body["channel"], "channel", C.CHANNELS)
    if "credit_limit_cents" in body:
        new_credit = as_int_at_least(body["credit_limit_cents"], "credit_limit_cents", 0)
    if "discount_pct" in body:
        new_discount = _check_discount(body["discount_pct"])
    customer["tier"] = new_tier
    customer["channel"] = new_channel
    customer["credit_limit_cents"] = new_credit
    customer["discount_pct"] = new_discount
    store.touch(customer)
    return success(customer_public(customer))
