"""Resale listings: creation, expiry, the markdown ladder and sale."""
from decimal import Decimal

from flask import Blueprint

import calc
import core
import serialize
import services
from core import (DB, LISTING_STATES, LISTING_TERMINAL, LISTING_WINDOW_DAYS,
                  MAX_MARKDOWN_STEPS, MAX_SALE_DISCOUNT_PCT, CHANNELS,
                  date_add, fail, now_iso, ok, ok_list, rhu, today_str)
from guards import (begin, body_json, enum_query, fk, lookup, pagination, paginate,
                    sort_rows, str_query, validate)

bp = Blueprint("resale", __name__)


def _apply_pricing(listing, unit):
    style = DB["styles"].get(unit["style_id"])
    priced = calc.resale_pricing(style, unit, listing["channel"],
                                 listing["markdown_step"])
    listing["base_price_cents"] = priced["base_price_cents"]
    listing["list_price_cents"] = priced["list_price_cents"]
    listing["channel_fee_cents"] = priced["channel_fee_cents"]
    listing["net_recovery_cents"] = priced["net_recovery_cents"]
    listing["floor_adjusted"] = priced["floor_adjusted"]
    listing["_tier"] = priced["tier"]
    listing["_fee_pct"] = priced["fee_pct"]
    return priced


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@bp.post("/resale-listings")
def create_listing():
    begin(["InventoryPlanner"])
    body = body_json()
    unit = fk(body, "rental_unit_id", "rental_units", "ERR_RENTAL_UNIT_NOT_FOUND")
    predecessor = fk(body, "supersedes_listing_id", "resale_listings",
                     "ERR_LISTING_NOT_FOUND")
    data = validate(body, [
        {"name": "rental_unit_id", "kind": "str", "required": True},
        {"name": "expected_rental_unit_version", "kind": "int", "required": True},
        {"name": "channel", "kind": "enum", "required": True,
         "values": CHANNELS},
        {"name": "supersedes_listing_id", "kind": "str", "default": None},
    ])
    # Rank 13
    if data["expected_rental_unit_version"] != unit["version"]:
        fail("ERR_STALE_UNIT_VERSION",
             "expected_rental_unit_version does not match the unit's version")
    # Rank 34
    if predecessor is not None:
        if (predecessor["rental_unit_id"] != unit["id"]
                or predecessor["state"] != "EXPIRED"):
            fail("ERR_INVALID_SUPERSEDE_TARGET",
                 "supersedes_listing_id must name an EXPIRED listing on this unit")
    # Rank 35
    for row in DB["resale_listings"].values():
        if row["rental_unit_id"] == unit["id"] and row["state"] in ("DRAFT",
                                                                   "LISTED"):
            fail("ERR_LISTING_ALREADY_ACTIVE",
                 "This unit already has an active resale listing")
    # Rank 46
    if unit["availability_state"] != "RETIRED":
        fail("ERR_UNIT_NOT_RETIRED", "Only a RETIRED unit may be listed for resale")

    listing = services.base_row("resale_listings")
    listing.update({
        "rental_unit_id": unit["id"],
        "supersedes_listing_id": predecessor["id"] if predecessor else None,
        "channel": data["channel"],
        "state": "DRAFT",
        "markdown_step": (predecessor["markdown_step"] + 1) if predecessor else 0,
        "base_price_cents": 0,
        "list_price_cents": 0,
        "channel_fee_cents": 0,
        "net_recovery_cents": 0,
        "floor_adjusted": False,
        "sale_price_cents": None,
        "listed_at": None,
        "sold_at": None,
    })
    _apply_pricing(listing, unit)
    # DRAFT -> LISTED inside the same request; never observable in DRAFT
    listing["state"] = "LISTED"
    listing["listed_at"] = now_iso()
    DB["resale_listings"][listing["id"]] = listing
    services.touch(unit)
    return ok(serialize.listing_out(listing), 201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/resale-listings/<listing_id>")
def get_listing(listing_id):
    begin(["InventoryPlanner", "PlatformAdmin"])
    row = lookup("resale_listings", listing_id, "ERR_LISTING_NOT_FOUND")
    return ok(serialize.listing_out(row))


@bp.get("/resale-listings")
def list_listings():
    begin(["InventoryPlanner", "PlatformAdmin"])
    channel = enum_query("channel", CHANNELS)
    state = enum_query("state", LISTING_STATES)
    unit_id = str_query("rental_unit_id")
    supersedes = str_query("supersedes_listing_id")
    limit, offset = pagination()
    rows = []
    for r in DB["resale_listings"].values():
        if unit_id is not None and r["rental_unit_id"] != unit_id:
            continue
        if supersedes is not None and r["supersedes_listing_id"] != supersedes:
            continue
        if channel is not None and r["channel"] != channel:
            continue
        if state is not None and r["state"] != state:
            continue
        rows.append(r)
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.listing_out)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Expiration
# ---------------------------------------------------------------------------
@bp.post("/resale-listings/<listing_id>/expiration")
def expire_listing(listing_id):
    begin(["InventoryPlanner"])
    listing = lookup("resale_listings", listing_id, "ERR_LISTING_NOT_FOUND")
    body_json()
    if listing["state"] in LISTING_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Listing is %s" % listing["state"])
    if listing["state"] != "LISTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Expiry is not declared from %s" % listing["state"])
    # Rank 44 — inclusive boundary on the thirtieth day
    listed_date = core.parse_instant(listing["listed_at"]).strftime("%Y-%m-%d")
    if today_str() < date_add(listed_date, LISTING_WINDOW_DAYS):
        fail("ERR_LISTING_WINDOW_OPEN", "The selling window has not yet elapsed")
    listing["state"] = "EXPIRED"
    services.touch(listing)
    return ok(serialize.listing_out(listing))


# ---------------------------------------------------------------------------
# Reprice / withdraw
# ---------------------------------------------------------------------------
@bp.post("/resale-listings/<listing_id>/reprice")
def reprice_listing(listing_id):
    begin(["InventoryPlanner"])
    listing = lookup("resale_listings", listing_id, "ERR_LISTING_NOT_FOUND")
    body_json()
    if listing["state"] in LISTING_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Listing is %s" % listing["state"])
    if listing["state"] != "EXPIRED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Reprice is not declared from %s" % listing["state"])
    unit = DB["rental_units"].get(listing["rental_unit_id"])
    if listing["markdown_step"] < MAX_MARKDOWN_STEPS:
        listing["markdown_step"] += 1
        if unit is not None:
            _apply_pricing(listing, unit)
        listing["state"] = "LISTED"
        listing["listed_at"] = now_iso()
    else:
        listing["state"] = "WITHDRAWN"
    services.touch(listing)
    return ok(serialize.listing_out(listing))


# ---------------------------------------------------------------------------
# Sale
# ---------------------------------------------------------------------------
@bp.post("/resale-listings/<listing_id>/sale")
def sell_listing(listing_id):
    begin(["InventoryPlanner"])
    listing = lookup("resale_listings", listing_id, "ERR_LISTING_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "sale_price_cents", "kind": "int", "required": True, "min": 0},
    ])
    if listing["state"] in LISTING_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Listing is %s" % listing["state"])
    if listing["state"] != "LISTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A sale is not declared from %s" % listing["state"])
    # Rank 55
    floor = rhu(Decimal(listing["list_price_cents"])
                * (Decimal(1) - MAX_SALE_DISCOUNT_PCT))
    if data["sale_price_cents"] < floor:
        fail("ERR_SALE_PRICE_BELOW_FLOOR",
             "sale_price_cents may not fall more than 10%% below the list price")
    listing["state"] = "SOLD"
    listing["sold_at"] = now_iso()
    listing["sale_price_cents"] = data["sale_price_cents"]
    restated = calc.resale_sale_math(listing["channel"], listing["_fee_pct"],
                                     data["sale_price_cents"])
    listing["channel_fee_cents"] = restated["channel_fee_cents"]
    listing["net_recovery_cents"] = restated["net_recovery_cents"]
    services.touch(listing)
    unit = DB["rental_units"].get(listing["rental_unit_id"])
    if unit is not None and unit["availability_state"] == "RETIRED":
        unit["availability_state"] = "SOLD"
        services.touch(unit)
    return ok(serialize.listing_out(listing))
