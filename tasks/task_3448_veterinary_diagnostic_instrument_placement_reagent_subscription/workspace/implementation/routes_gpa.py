"""Group pricing agreements: POST + GET list."""
from flask import Blueprint, request

import db
import ser
import services
import util
from constants import MAX_DISCOUNT_PCT, PRICE_TABLE
from errors import err

bp = Blueprint("gpa", __name__)


@bp.post("/api/group-pricing-agreements")
def create_gpa():
    _, role = util.auth()
    util.require(role, ["PlatformAdmin"])
    b = util.body()

    # Tier 5: input shape and referential integrity.
    group_type = b.get("group_type")
    if group_type not in ("CORPORATE", "BUYING"):
        raise err("ERR_INVALID_REQUEST", "group_type must be CORPORATE or BUYING")
    group_code = b.get("group_code")
    if not isinstance(group_code, str) or not group_code:
        raise err("ERR_INVALID_REQUEST", "group_code is required")
    try:
        eff_from = util.parse_iso(b.get("effective_from"))
        eff_to = util.parse_iso(b.get("effective_to"))
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST",
                  "effective_from and effective_to must be valid ISO 8601 timestamps")
    discount = b.get("discount_pct")
    if not util.is_num(discount):
        raise err("ERR_INVALID_REQUEST", "discount_pct is required")
    discount_dec = util.dec(discount)
    if discount_dec < 0 or discount_dec > MAX_DISCOUNT_PCT:
        raise err("ERR_INVALID_REQUEST",
                  "discount_pct must lie between 0 and 0.40 inclusive")
    overrides_in = b.get("sku_overrides", [])
    if not isinstance(overrides_in, list):
        raise err("ERR_INVALID_REQUEST", "sku_overrides must be an array")
    overrides = {}
    for entry in overrides_in:
        if not isinstance(entry, dict):
            raise err("ERR_INVALID_REQUEST", "sku_overrides entries must be objects")
        sku = entry.get("sku")
        if sku not in PRICE_TABLE:
            raise err("ERR_UNKNOWN_SKU", f"unknown sku in sku_overrides: {sku}")
        up = entry.get("unit_price_cents")
        if not util.is_int(up) or up < 0:
            raise err("ERR_INVALID_REQUEST",
                      "sku_overrides unit_price_cents must be a non-negative integer")
        overrides[sku] = up

    # Tier 8: window validity, then half-open overlap per (group_type, group_code).
    now = db.now()
    if not eff_to > eff_from:
        raise err("ERR_WINDOW_INVALID",
                  "effective_to must be strictly after effective_from")
    if not eff_to > now:
        raise err("ERR_WINDOW_INVALID",
                  "effective_to must be strictly after the logical clock")
    for g in db.gpas.values():
        if (g["group_type"] == group_type and g["group_code"] == group_code
                and g["status"] != "EXPIRED"
                and eff_from < g["_to"] and g["_from"] < eff_to):
            raise err("ERR_PRICING_AGREEMENT_WINDOW_OVERLAP",
                      "window overlaps a non-EXPIRED agreement with the same "
                      "group_type and group_code")

    g = services.stamp({
        "group_type": group_type,
        "group_code": group_code,
        "_from": eff_from,
        "_to": eff_to,
        "discount_pct": discount,
        "_discount_dec": discount_dec,
        "sku_overrides": overrides_in,
        "_overrides": overrides,
        "status": "ACTIVE" if eff_from <= now else "DRAFT",
    })
    db.gpas[g["id"]] = g
    return util.ok(ser.gpa(g), code=201)


@bp.get("/api/group-pricing-agreements")
def list_gpas():
    util.auth()
    items = util.sorted_items(db.gpas.values())
    gc = request.args.get("group_code")
    if gc is not None:
        items = [g for g in items if g["group_code"] == gc]
    st = request.args.get("status")
    if st is not None:
        items = [g for g in items if g["status"] == st]
    return util.paginate([ser.gpa(g) for g in items])
