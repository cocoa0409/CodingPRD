"""Baskets, basket lines and sealed bags (PRD sections 3.5 to 3.7)."""
from flask import Blueprint

import clock
import db
import response
from errors import ApiError
from middleware import actor, body, endpoint
from services import ledger, pricing, rent
from services.lookup import fetch, fetch_body, listing
from services.scope import (ALL_ROLES, STAFF_ROLES, bag_itinerary_id, ensure_owner,
                            line_itinerary_id, owned_predicate, sale_itinerary_id)
from services.validate import req_enum, req_int, req_string

bp = Blueprint("sales", __name__)

CHANNELS = ("IN_STORE", "PRE_ORDER")
SEAL_VALIDITY_HOURS = 96
LIVE_BAG_STATES = ("ISSUED", "INTACT_VERIFIED", "TAMPERED")


def _guard_terminal(sale):
    if sale["fulfillment_status"] == "VOIDED":
        raise ApiError("ERR_SALE_ALREADY_TERMINAL")


def _stock_item_for(terminal_id, product_id):
    for item in db.ordered(db.stock_items,
                           lambda s: s["terminal_id"] == terminal_id
                           and s["product_id"] == product_id):
        return item
    return None


def new_sale(itinerary, terminal, agreement, channel):
    sale = db.base()
    sale.update({
        "itinerary_id": itinerary["id"],
        "terminal_id": terminal["id"],
        "agreement_id": agreement["id"],
        "channel": channel,
        "fulfillment_status": "CART",
        "duty_status": "SUSPENDED",
        "effective_destination_country": None,
        "gross_amount_cents": 0,
        "exempt_amount_cents": 0,
        "duty_liability_cents": 0,
        "eligibility_variant": None,
        "sealed_bag_required": False,
        "arrival_advisory": [],
        "cleared_at": None,
        "picked_up_at": None,
        "voided_at": None,
    })
    db.sales[sale["id"]] = sale
    return sale


def new_line(sale, product, qty):
    line = db.base()
    line.update({
        "sale_id": sale["id"],
        "product_id": product["id"],
        "qty": qty,
        "unit_price_cents": product["unit_price_cents"],
        "line_total_cents": qty * product["unit_price_cents"],
        "allowance_excess_qty": 0,
        "line_exempt_cents": 0,
        "line_duty_cents": 0,
    })
    db.sale_lines[line["id"]] = line
    return line


# --------------------------------------------------------------------------
# Sales
# --------------------------------------------------------------------------
@bp.post("/sales")
@endpoint("SalesAssociate")
def create_sale():
    payload = body()
    itinerary = fetch_body("itineraries", "itinerary_id", payload)
    channel = req_enum(payload, "channel", CHANNELS)
    terminal = db.terminals[itinerary["departure_terminal_id"]]
    agreement = ledger.active_agreement(terminal["id"])
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    if not itinerary["is_international"]:
        raise ApiError("ERR_ITINERARY_NOT_INTERNATIONAL")
    sale = new_sale(itinerary, terminal, agreement, channel)
    return response.created(db.public(sale))


@bp.get("/sales/<sale_id>")
@endpoint(*ALL_ROLES)
def get_sale(sale_id):
    sale = fetch("sales", sale_id)
    ensure_owner(sale_itinerary_id(sale))
    return response.single(db.public(sale))


@bp.get("/sales")
@endpoint(*STAFF_ROLES)
def list_sales():
    rows, limit, offset, total = listing(
        db.sales,
        ("itinerary_id", "terminal_id", "agreement_id", "fulfillment_status", "duty_status"),
    )
    return response.collection(rows, limit, offset, total)


@bp.post("/sales/<sale_id>/lines")
@endpoint("SalesAssociate")
def add_line(sale_id):
    sale = fetch("sales", sale_id)
    payload = body()
    product = fetch_body("products", "product_id", payload)
    qty = req_int(payload, "qty", minimum=1)
    expected_version = req_int(payload, "expected_sale_version")
    _guard_terminal(sale)
    if sale["fulfillment_status"] != "CART":
        raise ApiError("ERR_SALE_NOT_IN_CART")
    if product["assortment_status"] != "LISTED":
        raise ApiError("ERR_PRODUCT_NOT_LISTED")
    if expected_version != sale["version"]:
        raise ApiError("ERR_STALE_SALE_VERSION")
    item = _stock_item_for(sale["terminal_id"], product["id"])
    if item is None:
        raise ApiError("ERR_TERMINAL_MISMATCH")
    if item["available_qty"] < qty:
        raise ApiError("ERR_BONDED_STOCK_INSUFFICIENT")
    line = new_line(sale, product, qty)
    pricing.recompute_gross(sale)
    db.touch(sale)
    return response.created(db.public(line))


@bp.get("/sale-lines/<sale_line_id>")
@endpoint(*ALL_ROLES)
def get_sale_line(sale_line_id):
    line = fetch("sale_lines", sale_line_id)
    ensure_owner(line_itinerary_id(line))
    return response.single(db.public(line))


@bp.get("/sale-lines")
@endpoint(*ALL_ROLES)
def list_sale_lines():
    rows, limit, offset, total = listing(
        db.sale_lines, ("sale_id", "product_id"), owned_predicate(line_itinerary_id))
    return response.collection(rows, limit, offset, total)


@bp.post("/sales/<sale_id>/clear-eligibility")
@endpoint("SalesAssociate")
def clear_eligibility(sale_id):
    sale = fetch("sales", sale_id)
    _guard_terminal(sale)
    if sale["fulfillment_status"] != "CART":
        raise ApiError("ERR_SALE_NOT_IN_CART")
    itinerary = db.itineraries[sale["itinerary_id"]]
    if itinerary["scan_status"] not in ("SCANNED", "AMENDED"):
        raise ApiError("ERR_ITINERARY_NOT_SCANNED")
    destination = pricing.effective_destination(itinerary, pricing.SUSPENDED_ESTIMATE)
    pricing.require_rules(sale, destination)
    if clock.now() >= clock.parse(itinerary["departure_utc"]):
        raise ApiError("ERR_DEPARTURE_PASSED")
    if not itinerary["is_international"]:
        raise ApiError("ERR_ITINERARY_NOT_INTERNATIONAL")
    if not pricing.lines_of(sale):
        raise ApiError("ERR_EMPTY_BASKET")
    pricing.price(sale, pricing.SUSPENDED_ESTIMATE)
    sale["sealed_bag_required"] = pricing.sealed_bag_required(sale)
    sale["fulfillment_status"] = "ELIGIBILITY_CLEARED"
    sale["cleared_at"] = clock.now_iso()
    db.touch(sale)
    return response.single(db.public(sale))


@bp.post("/sales/<sale_id>/pickup")
@endpoint("SalesAssociate")
def pickup_sale(sale_id):
    sale = fetch("sales", sale_id)
    _guard_terminal(sale)
    if sale["fulfillment_status"] != "ELIGIBILITY_CLEARED":
        raise ApiError("ERR_SALE_NOT_CLEARED")
    itinerary = db.itineraries[sale["itinerary_id"]]
    if itinerary["scan_status"] not in ("SCANNED", "AMENDED"):
        raise ApiError("ERR_ITINERARY_NOT_SCANNED")
    if sale["sealed_bag_required"]:
        verified = [b for b in db.sealed_bags.values()
                    if b["sale_id"] == sale["id"] and b["status"] == "INTACT_VERIFIED"]
        if not verified:
            raise ApiError("ERR_SEALED_BAG_REQUIRED")
    destination = pricing.effective_destination(itinerary, pricing.EXEMPT_CONFIRMED_FINAL)
    pricing.require_rules(sale, destination)
    if clock.now() >= clock.parse(itinerary["departure_utc"]):
        raise ApiError("ERR_DEPARTURE_PASSED")
    lines = pricing.lines_of(sale)
    for line in lines:
        item = _stock_item_for(sale["terminal_id"], line["product_id"])
        if item is None or item["available_qty"] < line["qty"]:
            raise ApiError("ERR_BONDED_STOCK_INSUFFICIENT")
    # level 1: the accounting is finalised
    pricing.price(sale, pricing.EXEMPT_CONFIRMED_FINAL)
    sale["duty_status"] = "EXEMPT_CONFIRMED" if sale["duty_liability_cents"] == 0 else "DUTY_LIABLE"
    sale["fulfillment_status"] = "PICKED_UP"
    sale["picked_up_at"] = clock.now_iso()
    db.touch(sale)
    # level 2: the goods leave bond
    for line in lines:
        item = _stock_item_for(sale["terminal_id"], line["product_id"])
        ledger.append(item, "SALE_ISSUE", -line["qty"], "SALE", sale["id"], actor())
    # levels 3 and 4: the concession ledger and the rent basis
    agreement = db.agreements.get(sale["agreement_id"])
    if agreement is not None:
        agreement["gross_sales_cents"] += sale["gross_amount_cents"]
        rent.recompute_accrual(agreement)
        db.touch(agreement)
    return response.single(db.public(sale))


@bp.post("/sales/<sale_id>/void")
@endpoint("SalesAssociate")
def void_sale(sale_id):
    sale = fetch("sales", sale_id)
    _guard_terminal(sale)
    was_picked_up = sale["fulfillment_status"] == "PICKED_UP"
    agreement = db.agreements.get(sale["agreement_id"])
    if was_picked_up and (agreement is None or agreement["status"] != "ACTIVE"):
        raise ApiError("ERR_VOID_AFTER_PERIOD_CLOSE")
    sale["fulfillment_status"] = "VOIDED"
    sale["duty_status"] = "REVERSED"
    sale["voided_at"] = clock.now_iso()
    sale["exempt_amount_cents"] = 0
    sale["duty_liability_cents"] = 0
    db.touch(sale)
    if was_picked_up:
        originals = db.ordered(db.movements,
                               lambda m: m["movement_type"] == "SALE_ISSUE"
                               and m["source_ref_id"] == sale["id"]
                               and not m["reversed"])
        for original in originals:
            item = db.stock_items[original["stock_item_id"]]
            ledger.append(item, "REVERSAL", -original["qty_delta"], "SALE", sale["id"],
                          actor(), original=original)
        agreement["gross_sales_cents"] -= sale["gross_amount_cents"]
        rent.recompute_accrual(agreement)
        db.touch(agreement)
    for bag in db.ordered(db.sealed_bags,
                          lambda b: b["sale_id"] == sale["id"]
                          and b["status"] in LIVE_BAG_STATES):
        if bag["status"] == "ISSUED":
            bag["verified_at"] = clock.now_iso()
        bag["status"] = "VOIDED"
        db.touch(bag)
    return response.single(db.public(sale))


# --------------------------------------------------------------------------
# Sealed bags
# --------------------------------------------------------------------------
@bp.post("/sealed-bags")
@endpoint("SalesAssociate")
def issue_sealed_bag():
    payload = body()
    sale = fetch_body("sales", "sale_id", payload)
    seal_number = req_string(payload, "seal_number")
    for existing in db.sealed_bags.values():
        if existing["seal_number"] == seal_number:
            raise ApiError("ERR_DUPLICATE_SEAL_NUMBER")
    if sale["fulfillment_status"] != "ELIGIBILITY_CLEARED":
        raise ApiError("ERR_SALE_NOT_CLEARED")
    itinerary = db.itineraries[sale["itinerary_id"]]
    terminal = db.terminals[sale["terminal_id"]]
    total_liquid_ml = pricing.total_liquid_ml(sale)
    expires_at = clock.plus_hours(clock.parse(itinerary["departure_utc"]), SEAL_VALIDITY_HOURS)
    if total_liquid_ml > terminal["liquid_limit_ml"]:
        raise ApiError("ERR_LIQUID_LIMIT_EXCEEDED")
    if itinerary["has_connection"] and itinerary["connection_departure_utc"]:
        if clock.parse(itinerary["connection_departure_utc"]) > expires_at:
            raise ApiError("ERR_SEAL_WINDOW_EXPIRED")
    bag = db.base()
    bag.update({
        "sale_id": sale["id"],
        "terminal_id": sale["terminal_id"],
        "seal_number": seal_number,
        "status": "ISSUED",
        "total_liquid_ml": total_liquid_ml,
        "issued_at": clock.now_iso(),
        "expires_at": clock.fmt(expires_at),
        "verified_at": None,
    })
    db.sealed_bags[bag["id"]] = bag
    return response.created(db.public(bag))


@bp.get("/sealed-bags/<sealed_bag_id>")
@endpoint(*ALL_ROLES)
def get_sealed_bag(sealed_bag_id):
    bag = fetch("sealed_bags", sealed_bag_id)
    ensure_owner(bag_itinerary_id(bag))
    return response.single(db.public(bag))


@bp.get("/sealed-bags")
@endpoint(*ALL_ROLES)
def list_sealed_bags():
    rows, limit, offset, total = listing(
        db.sealed_bags, ("sale_id", "terminal_id", "status"),
        owned_predicate(bag_itinerary_id))
    return response.collection(rows, limit, offset, total)


@bp.post("/sealed-bags/<sealed_bag_id>/verify")
@endpoint("SalesAssociate")
def verify_sealed_bag(sealed_bag_id):
    bag = fetch("sealed_bags", sealed_bag_id)
    outcome = req_enum(body(), "outcome", ("INTACT", "TAMPERED"))
    if bag["status"] != "ISSUED":
        raise ApiError("ERR_BAG_NOT_ISSUED")
    sale = db.sales[bag["sale_id"]]
    if sale["fulfillment_status"] != "ELIGIBILITY_CLEARED":
        raise ApiError("ERR_SALE_NOT_CLEARED")
    if clock.now() > clock.parse(bag["expires_at"]):
        raise ApiError("ERR_SEAL_WINDOW_EXPIRED")
    bag["status"] = "INTACT_VERIFIED" if outcome == "INTACT" else "TAMPERED"
    bag["verified_at"] = clock.now_iso()
    db.touch(bag)
    if outcome == "TAMPERED" and sale["duty_status"] == "SUSPENDED":
        sale["duty_status"] = "DUTY_LIABLE"
        pricing.forfeit(sale)
        db.touch(sale)
    return response.single(db.public(bag))
