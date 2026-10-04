"""Numismatic product catalog: creation rules, release lifecycle, withdrawal
(PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import serialize
import store
from helpers import (auth, bad_request, body, envelope, err, list_response,
                     need_datetime, need_enum, need_int, need_str,
                     no_undeclared, not_found, opt_bool, opt_str, try_datetime)

bp = Blueprint("products", __name__)

PRODUCT_TYPES = {"PROOF_SET", "COMMEMORATIVE", "UNCIRCULATED", "SUBSCRIPTION_SERIES"}
RELEASE_MIN_GAP = timedelta(hours=24)


def refresh_sale_status(product):
    """SOLD_OUT <-> ON_SALE driven by allocated_units vs mintage_limit
    (equality closes; dipping below reopens)."""
    alloc = serialize.allocated_units(product["id"])
    if product["status"] == "ON_SALE" and alloc == product["mintage_limit"]:
        product["status"] = "SOLD_OUT"
        store.bump(product)
    elif product["status"] == "SOLD_OUT" and alloc < product["mintage_limit"]:
        product["status"] = "ON_SALE"
        store.bump(product)


@bp.route("/mint/products", methods=["POST"])
def create_product():
    auth("ProgramManager")
    b = body()
    # Rung 6: a supplied program_id must resolve.
    program_id = b.get("program_id")
    if isinstance(program_id, str) and program_id not in store.db["programs"]:
        err("ERR_UNKNOWN_PROGRAM", 422, "Unknown program_id")
    # Rung 8: release gap within the family (>= 24h passes; < 24h fails)
    # against non-WITHDRAWN products.
    rel_dt, _raw = try_datetime(b, "release_datetime")
    family = b.get("product_family")
    if rel_dt is not None and isinstance(family, str):
        for q in store.db["products"].values():
            if q["product_family"] == family and q["status"] != "WITHDRAWN":
                if abs(q["_release_dt"] - rel_dt) < RELEASE_MIN_GAP:
                    err("ERR_RELEASE_GAP_VIOLATION", 409,
                        "Releases within a family must stand at least 24 hours apart")
    # Rung 9: shape.
    no_undeclared(b, {"product_code", "program_id", "product_family",
                      "product_type", "price_cents", "mintage_limit",
                      "household_order_limit", "release_datetime",
                      "subscription_eligible"})
    code = need_str(b, "product_code")
    if program_id is not None and not isinstance(program_id, str):
        bad_request("program_id must be a string when supplied")
    family = need_str(b, "product_family")
    ptype = need_enum(b, "product_type", PRODUCT_TYPES)
    price = need_int(b, "price_cents")
    if price <= 0:
        bad_request("price_cents must be strictly positive")
    mintage = need_int(b, "mintage_limit")
    if mintage <= 0:
        bad_request("mintage_limit must be strictly positive")
    household_limit = need_int(b, "household_order_limit")
    if household_limit <= 0:
        bad_request("household_order_limit must be strictly positive")
    rel_dt, rel_raw = need_datetime(b, "release_datetime")
    eligible = opt_bool(b, "subscription_eligible", default=False)
    if code in [p["product_code"] for p in store.db["products"].values()]:
        err("ERR_PRODUCT_CODE_EXISTS", 409, "product_code already exists")
    # Program mintage ceiling: sum of mintage_limit over the program's
    # products plus the new product must stay at or below max_mintage_legal.
    if program_id is not None:
        prog = store.db["programs"][program_id]
        used = sum(p["mintage_limit"] for p in store.db["products"].values()
                   if p["program_id"] == program_id)
        if used + mintage > prog["max_mintage_legal"]:
            err("ERR_PROGRAM_MINTAGE_EXCEEDED", 422,
                "Program mintage ceiling would be exceeded")
    p = store.mint_entity({
        "product_code": code,
        "program_id": program_id,
        "product_family": family,
        "product_type": ptype,
        "price_cents": price,
        "mintage_limit": mintage,
        "household_order_limit": household_limit,
        "release_datetime": rel_raw,
        "_release_dt": rel_dt,
        "subscription_eligible": eligible,
        "status": "SCHEDULED",
    })
    store.db["products"][p["id"]] = p
    return envelope(serialize.product(p), status=201)


@bp.route("/mint/products", methods=["GET"])
def list_products():
    auth("Collector", "ProgramManager", "MintDirector", "FinanceOfficer",
         "PlatformAdmin")
    items = list(store.db["products"].values())
    for param in ("program_id", "status", "product_family"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p[param] == v]
    return list_response(items, serialize.product)


def _get_product_or_404(pid):
    p = store.db["products"].get(pid)
    if p is None:
        not_found("Product not found")
    return p


@bp.route("/mint/products/<pid>", methods=["GET"])
def get_product(pid):
    auth("Collector", "ProgramManager", "MintDirector", "FinanceOfficer",
         "PlatformAdmin")
    return envelope(serialize.product(_get_product_or_404(pid)))


@bp.route("/mint/products/<pid>/withdraw", methods=["POST"])
def withdraw_product(pid):
    auth("ProgramManager")
    p = _get_product_or_404(pid)
    live_sub = any(s["product_id"] == p["id"] and s["status"] in ("ACTIVE", "DUNNING")
                   for s in store.db["subscriptions"].values())
    if p["status"] == "WITHDRAWN" or live_sub:
        err("ERR_PRODUCT_NOT_WITHDRAWABLE", 422,
            "Product is withdrawn or still referenced by a live subscription")
    no_undeclared(body(), set())
    # Cascade: ALLOCATED/WAITLISTED orders are RELEASED (derived status
    # CANCELLED); PAID ones are refunded. No waitlist promotion runs.
    for o in store.db["orders"].values():
        if o["product_id"] != p["id"]:
            continue
        if o["allocation_status"] in ("ALLOCATED", "WAITLISTED"):
            o["allocation_status"] = "RELEASED"
            if o["payment_status"] == "PAID":
                o["payment_status"] = "REFUNDED"
            store.bump(o)
    p["status"] = "WITHDRAWN"
    store.bump(p)
    return envelope(serialize.product(p))
