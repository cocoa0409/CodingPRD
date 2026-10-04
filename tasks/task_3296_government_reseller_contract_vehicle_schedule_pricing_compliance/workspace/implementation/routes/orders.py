"""Order surface: intake, screening, delivery, cancellation."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from server_core import app
from errors import (
    err, not_found, invalid_state, fk_not_found,
    ERR_AGREEMENT_NOT_GOOD_STANDING, ERR_ORDER_LINE_INVALID,
    ERR_STALE_ORDER_VERSION, ERR_TAA_ORIGIN_VIOLATION,
)
from util import envelope, respond_list, body_arg, new_entity, bump, now_logical
from rules import (
    TIERS, maybe_expire_vehicle, resolve_agreement_of_vehicle,
    resolve_manufacturer_of_agreement, assert_active_list_for_order,
    assert_agreement_good_standing, assert_vehicle_window_open,
    assert_teaming_eligible, compute_origin_flag, teaming_surcharge_cents,
    deliver_ceiling_check, recompute_prc, recompute_sales_report, cancel_order,
)


def order_view(o):
    return {k: o[k] for k in ("id", "vehicle_id", "price_list_id", "teaming_id", "buyer_tier",
                              "lines", "order_total_cents", "teaming_surcharge_cents",
                              "subcontract_cents", "compliance_status", "billing_status",
                              "origin_flag", "created_at", "updated_at", "version")}


def get_order(oid):
    o = db.orders.get(oid)
    if o is None:
        raise not_found("order not found")
    return o


@app.post("/orders")
def orders_create():
    vehicle_id = body_arg("vehicle_id")
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise fk_not_found("vehicle_id not found")
    maybe_expire_vehicle(db, vehicle)
    price_list_id = body_arg("price_list_id")
    if price_list_id not in db.price_lists:
        raise fk_not_found("price_list_id not found")
    active = assert_active_list_for_order(db, vehicle, price_list_id)
    teaming_id = body_arg("teaming_id")
    teaming = None
    if teaming_id is not None:
        teaming = db.teaming.get(teaming_id)
        if teaming is None:
            raise fk_not_found("teaming_id not found")
    lines = body_arg("lines") or []
    if not isinstance(lines, list) or not (1 <= len(lines) <= 100):
        raise err(ERR_ORDER_LINE_INVALID, "order must carry between 1 and 100 lines", 422)
    pl_by_sku = {l["sku"]: l for l in db.price_lines.values() if l["price_list_id"] == active["id"]}
    skus = []
    total = 0
    for line in lines:
        sku = line.get("sku")
        qty = line.get("qty")
        pl = pl_by_sku.get(sku)
        if pl is None or not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise err(ERR_ORDER_LINE_INVALID, "every sku must exist on the pinned list and qty must be positive", 422)
        skus.append(sku)
        subtotal = int((Decimal(int(pl["offered_price_cents"])) * Decimal(qty)).to_integral_value(rounding=ROUND_HALF_UP))
        total += subtotal
    if teaming is not None:
        assert_teaming_eligible(db, teaming, vehicle_id, skus)
    buyer_tier = body_arg("buyer_tier")
    if buyer_tier not in TIERS:
        raise err(ERR_ORDER_LINE_INVALID, "buyer_tier must be one of the five declared tiers", 422)
    surcharge = teaming_surcharge_cents(total, teaming)
    o = new_entity(db, db.orders, {},
                   vehicle_id=vehicle_id, price_list_id=price_list_id,
                   teaming_id=teaming_id, buyer_tier=buyer_tier, lines=lines,
                   order_total_cents=total, teaming_surcharge_cents=surcharge,
                   subcontract_cents=0, compliance_status="DRAFT",
                   billing_status="UNBILLED", origin_flag="NOT_APPLICABLE")
    o["_delivered_at"] = None
    return envelope(order_view(o), 201)


@app.get("/orders")
def orders_list():
    items = list(db.orders.values())
    vid = request.args.get("vehicle_id")
    if vid is not None:
        items = [o for o in items if o["vehicle_id"] == vid]
    cs = request.args.get("compliance_status")
    if cs is not None:
        items = [o for o in items if o["compliance_status"] == cs]
    bs = request.args.get("billing_status")
    if bs is not None:
        items = [o for o in items if o["billing_status"] == bs]
    bt = request.args.get("buyer_tier")
    if bt is not None:
        items = [o for o in items if o["buyer_tier"] == bt]
    return respond_list([order_view(o) for o in items])


@app.get("/orders/<oid>")
def orders_get(oid):
    return envelope(order_view(get_order(oid)), 200)


@app.post("/orders/<oid>/submit")
def orders_submit(oid):
    o = get_order(oid)
    if o["compliance_status"] != "DRAFT":
        raise invalid_state("order compliance dimension is not DRAFT")
    vehicle = db.vehicles[o["vehicle_id"]]
    maybe_expire_vehicle(db, vehicle)
    assert_vehicle_window_open(db, vehicle)
    if vehicle["status"] != "AUTHORIZED":
        raise invalid_state("vehicle is not AUTHORIZED")
    agreement = resolve_agreement_of_vehicle(db, vehicle)
    if agreement["posture"] != "GOOD_STANDING":
        raise err(ERR_AGREEMENT_NOT_GOOD_STANDING, "agreement posture is not GOOD_STANDING", 422)
    if db.price_lists[o["price_list_id"]]["status"] != "ACTIVE":
        raise err("ERR_PRICE_LIST_NOT_ACTIVE", "pinned price list is not ACTIVE", 422)
    skus = [l.get("sku") for l in o["lines"]]
    teaming = db.teaming.get(o["teaming_id"]) if o.get("teaming_id") else None
    if teaming is not None:
        assert_teaming_eligible(db, teaming, o["vehicle_id"], skus)
    pl_by_sku = {l["sku"]: l for l in db.price_lines.values() if l["price_list_id"] == o["price_list_id"]}
    origins = [pl_by_sku[s]["origin_country"] for s in skus]
    manufacturer = resolve_manufacturer_of_agreement(db, agreement)
    o["origin_flag"] = compute_origin_flag(db, vehicle, manufacturer, origins)
    bump(o)
    if o["origin_flag"] == "TAA_FAIL":
        raise err(ERR_TAA_ORIGIN_VIOLATION, "order line origin fails TAA evaluation for this vehicle", 422)
    if o["buyer_tier"] in vehicle["buyer_tiers"]:
        o["compliance_status"] = "CLEARED"
    else:
        o["compliance_status"] = "BLOCKED"
    bump(o)
    return envelope(order_view(o), 200)


@app.post("/orders/<oid>/deliver")
def orders_deliver(oid):
    o = get_order(oid)
    if o["compliance_status"] != "CLEARED" or o["billing_status"] != "UNBILLED":
        raise invalid_state("order must be CLEARED and UNBILLED to deliver")
    vehicle = db.vehicles[o["vehicle_id"]]
    maybe_expire_vehicle(db, vehicle)
    deliver_ceiling_check(db, vehicle, o)
    pl_by_sku = {l["sku"]: l for l in db.price_lines.values() if l["price_list_id"] == o["price_list_id"]}
    for line in o["lines"]:
        pl_by_sku[line["sku"]]["sold_qty"] += line["qty"]
    recompute_prc(db, o["vehicle_id"])
    teaming = db.teaming.get(o["teaming_id"]) if o.get("teaming_id") else None
    if teaming is not None and teaming["small_business"]:
        o["subcontract_cents"] = o["order_total_cents"]
    o["billing_status"] = "DELIVERED"
    o["_delivered_at"] = now_logical(db)
    bump(o)
    return envelope(order_view(o), 200)


@app.post("/orders/<oid>/cancel")
def orders_cancel(oid):
    o = get_order(oid)
    expected = body_arg("expected_order_version")
    if expected != o["version"]:
        raise err(ERR_STALE_ORDER_VERSION, "expected_order_version does not match current version", 412)
    if o["billing_status"] != "UNBILLED" or o["compliance_status"] in ("CANCELLED", "BLOCKED"):
        raise invalid_state("order cannot be cancelled in its current state")
    cancel_order(db, o)
    return envelope(order_view(o), 200)


@app.get("/orders/<oid>/invoices")
def orders_invoices(oid):
    get_order(oid)
    from routes.billing import invoice_view
    items = [i for i in db.invoices.values() if i["order_id"] == oid]
    return respond_list([invoice_view(i) for i in items])


@app.get("/orders/<oid>/disputes")
def orders_disputes(oid):
    get_order(oid)
    from routes.billing import dispute_view
    items = [d for d in db.disputes.values() if d["order_id"] == oid]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return respond_list([dispute_view(d) for d in items])
