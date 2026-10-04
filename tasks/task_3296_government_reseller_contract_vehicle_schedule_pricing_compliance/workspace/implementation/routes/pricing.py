"""PriceList, PriceLine, PriceModification surface."""
from flask import request

import db
from server_core import app
from errors import (
    err, not_found, invalid_state, fk_not_found,
    ERR_INVALID_PRICE_PERIOD, ERR_MFC_FLOOR_VIOLATION, ERR_SCOPE_VIOLATION,
    ERR_SOD_VIOLATION, ERR_STALE_PRICE_LIST_VERSION, ERR_TAA_ORIGIN_VIOLATION,
    ERR_UNIQUENESS_VIOLATION,
)
from util import envelope, respond_list, body_arg, new_entity, bump, parse_iso, now_logical
from rules import (
    maybe_expire_vehicle, resolve_agreement_of_vehicle, resolve_manufacturer_of_agreement,
    active_price_list_for_vehicle, mfc_floor_ok, compute_origin_flag_for_origin,
    sku_matches_scope, recompute_prc, teaming_surcharge_cents,
)


def price_list_view(p):
    return {k: p[k] for k in ("id", "vehicle_id", "submitted_by", "period_from", "period_to",
                              "status", "created_at", "updated_at", "version")}


def price_line_view(l):
    return {k: l[k] for k in ("id", "price_list_id", "sku", "basis_price_cents",
                              "offered_price_cents", "origin_country", "sold_qty", "created_at")}


def price_mod_view(m):
    return {k: m[k] for k in ("id", "price_list_id", "sku", "new_offered_price_cents",
                              "reason_code", "expected_price_list_version", "status", "created_by",
                              "created_at", "updated_at", "version")}


def get_price_list(pid):
    p = db.price_lists.get(pid)
    if p is None:
        raise not_found("price list not found")
    return p


def period_check(vehicle, pf, pt):
    pfs, pts = parse_iso(pf), parse_iso(pt)
    if pfs is None or pts is None or not (pfs < pts):
        raise err(ERR_INVALID_PRICE_PERIOD, "price period must be non-empty (period_from < period_to)", 422)
    if vehicle["_from"] is None or vehicle["_to"] is None or not (pfs < vehicle["_to"] and pts > vehicle["_from"]):
        raise err(ERR_INVALID_PRICE_PERIOD, "price period must intersect the vehicle effective window", 422)
    return pfs, pts


@app.post("/price-lists")
def price_lists_create():
    vehicle_id = body_arg("vehicle_id")
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise fk_not_found("vehicle_id not found")
    maybe_expire_vehicle(db, vehicle)
    period_check(vehicle, body_arg("period_from"), body_arg("period_to"))
    p = new_entity(db, db.price_lists, {},
                   vehicle_id=vehicle_id,
                   submitted_by=request.headers.get("X-User-ID"),
                   period_from=body_arg("period_from"),
                   period_to=body_arg("period_to"),
                   status="DRAFT")
    for line in (body_arg("lines") or []):
        new_entity(db, db.price_lines, {}, common=False,
                   price_list_id=p["id"],
                   sku=line.get("sku"),
                   basis_price_cents=line.get("basis_price_cents"),
                   offered_price_cents=line.get("offered_price_cents"),
                   origin_country=line.get("origin_country"),
                   sold_qty=0)
    return envelope(price_list_view(p), 201)


@app.get("/price-lists")
def price_lists_list():
    items = list(db.price_lists.values())
    vid = request.args.get("vehicle_id")
    if vid is not None:
        items = [p for p in items if p["vehicle_id"] == vid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return respond_list([price_list_view(p) for p in items])


@app.get("/price-lists/<pid>")
def price_lists_get(pid):
    return envelope(price_list_view(get_price_list(pid)), 200)


@app.get("/price-lists/<pid>/lines")
def price_lists_lines(pid):
    get_price_list(pid)
    items = [l for l in db.price_lines.values() if l["price_list_id"] == pid]
    return respond_list([price_line_view(l) for l in items])


@app.post("/price-lists/<pid>/submit")
def price_lists_submit(pid):
    p = get_price_list(pid)
    if p["status"] != "DRAFT":
        raise invalid_state("price list is not DRAFT")
    vehicle = db.vehicles[p["vehicle_id"]]
    maybe_expire_vehicle(db, vehicle)
    if vehicle["status"] != "AUTHORIZED":
        raise invalid_state("vehicle is not AUTHORIZED")
    if not any(l["price_list_id"] == pid for l in db.price_lines.values()):
        raise invalid_state("price list has no lines")
    period_check(vehicle, p["period_from"], p["period_to"])
    p["status"] = "SUBMITTED"
    bump(p)
    return envelope(price_list_view(p), 200)


@app.post("/price-lists/<pid>/activate")
def price_lists_activate(pid):
    p = get_price_list(pid)
    if p["status"] != "SUBMITTED":
        raise invalid_state("price list is not SUBMITTED")
    vehicle = db.vehicles[p["vehicle_id"]]
    maybe_expire_vehicle(db, vehicle)
    if vehicle["status"] != "AUTHORIZED":
        raise invalid_state("vehicle is not AUTHORIZED")
    agreement = resolve_agreement_of_vehicle(db, vehicle)
    manufacturer = resolve_manufacturer_of_agreement(db, agreement)
    lines = [l for l in db.price_lines.values() if l["price_list_id"] == pid]
    for l in lines:
        if not mfc_floor_ok(agreement, vehicle, l["basis_price_cents"], l["offered_price_cents"]):
            raise err(ERR_MFC_FLOOR_VIOLATION, "offered price exceeds the MFC floor", 422)
    for l in lines:
        if not compute_origin_flag_for_origin(vehicle, manufacturer, l["origin_country"]):
            raise err(ERR_TAA_ORIGIN_VIOLATION, "price line origin fails TAA evaluation for this vehicle", 422)
    for l in lines:
        if not sku_matches_scope(l["sku"], agreement["product_scope"]):
            raise err(ERR_SCOPE_VIOLATION, "price line sku is outside the agreement product scope", 422)
    superseded = None
    for other in db.price_lists.values():
        if other["vehicle_id"] == p["vehicle_id"] and other["status"] == "ACTIVE" and other["id"] != pid:
            superseded = other
    p["status"] = "ACTIVE"
    bump(p)
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        bump(superseded)
    recompute_prc(db, p["vehicle_id"])
    return envelope(price_list_view(p), 200)


@app.post("/price-lists/<pid>/reject")
def price_lists_reject(pid):
    p = get_price_list(pid)
    if p["status"] != "SUBMITTED":
        raise invalid_state("price list is not SUBMITTED")
    p["status"] = "REJECTED"
    bump(p)
    return envelope(price_list_view(p), 200)


@app.post("/price-lists/<pid>/reopen")
def price_lists_reopen(pid):
    p = get_price_list(pid)
    if p["status"] != "ACTIVE":
        raise invalid_state("price list is not ACTIVE")
    for o in db.orders.values():
        if o["price_list_id"] == pid and o["billing_status"] in ("DELIVERED", "INVOICED", "PAID"):
            raise invalid_state("orders pinned to this list have already been delivered or invoiced")
    p["status"] = "DRAFT"
    bump(p)
    recompute_prc(db, p["vehicle_id"])
    return envelope(price_list_view(p), 200)


@app.get("/price-lists/<pid>/orders")
def price_lists_orders(pid):
    get_price_list(pid)
    from routes.orders import order_view
    items = [o for o in db.orders.values() if o["price_list_id"] == pid]
    return respond_list([order_view(o) for o in items])


@app.get("/price-lists/<pid>/modifications")
def price_lists_mods(pid):
    get_price_list(pid)
    items = [m for m in db.price_modifications.values() if m["price_list_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return respond_list([price_mod_view(m) for m in items])


@app.post("/price-modifications")
def price_mods_create():
    price_list_id = body_arg("price_list_id")
    p = db.price_lists.get(price_list_id)
    if p is None:
        raise fk_not_found("price_list_id not found")
    sku = body_arg("sku")
    line = next((l for l in db.price_lines.values()
                 if l["price_list_id"] == price_list_id and l["sku"] == sku), None)
    if line is None:
        raise fk_not_found("sku not found on the price list")
    expected = body_arg("expected_price_list_version")
    if expected != p["version"]:
        raise err(ERR_STALE_PRICE_LIST_VERSION, "expected_price_list_version does not match current version", 412)
    m = new_entity(db, db.price_modifications, {},
                   price_list_id=price_list_id, sku=sku,
                   new_offered_price_cents=body_arg("new_offered_price_cents"),
                   reason_code=body_arg("reason_code"),
                   expected_price_list_version=expected,
                   status="PENDING",
                   created_by=request.headers.get("X-User-ID"))
    return envelope(price_mod_view(m), 201)


@app.get("/price-modifications/<mid>")
def price_mods_get(mid):
    m = db.price_modifications.get(mid)
    if m is None:
        raise not_found("price modification not found")
    return envelope(price_mod_view(m), 200)


@app.post("/price-modifications/<mid>/approve")
def price_mods_approve(mid):
    m = db.price_modifications.get(mid)
    if m is None:
        raise not_found("price modification not found")
    if m["status"] != "PENDING":
        raise invalid_state("price modification is not PENDING")
    p = db.price_lists[m["price_list_id"]]
    if p["status"] != "ACTIVE":
        raise invalid_state("price list is not ACTIVE")
    vehicle = db.vehicles[p["vehicle_id"]]
    agreement = resolve_agreement_of_vehicle(db, vehicle)
    line = next(l for l in db.price_lines.values()
                if l["price_list_id"] == p["id"] and l["sku"] == m["sku"])
    if not mfc_floor_ok(agreement, vehicle, line["basis_price_cents"], m["new_offered_price_cents"]):
        raise err(ERR_MFC_FLOOR_VIOLATION, "new offered price exceeds the MFC floor", 422)
    if request.headers.get("X-User-ID") == m.get("created_by"):
        raise err(ERR_SOD_VIOLATION, "price-modification approver must differ from proposer", 422)
    line["offered_price_cents"] = m["new_offered_price_cents"]
    m["status"] = "APPROVED"
    bump(m)
    bump(p)
    recompute_prc(db, p["vehicle_id"])
    # Lower offered price before delivery retroactively reduces the surcharge
    # on teaming-routed orders not yet delivered.
    for o in db.orders.values():
        if o["price_list_id"] == p["id"] and o["billing_status"] == "UNBILLED" and o.get("teaming_id"):
            arrangement = db.teaming.get(o["teaming_id"])
            o["teaming_surcharge_cents"] = teaming_surcharge_cents(o["order_total_cents"], arrangement)
    return envelope(price_mod_view(m), 200)


@app.post("/price-modifications/<mid>/reject")
def price_mods_reject(mid):
    m = db.price_modifications.get(mid)
    if m is None:
        raise not_found("price modification not found")
    if m["status"] != "PENDING":
        raise invalid_state("price modification is not PENDING")
    m["status"] = "REJECTED"
    bump(m)
    return envelope(price_mod_view(m), 200)
