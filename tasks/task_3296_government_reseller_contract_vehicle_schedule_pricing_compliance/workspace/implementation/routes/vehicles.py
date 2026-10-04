"""ContractVehicle surface."""
from flask import request

import db
from server_core import app
from errors import (
    err, not_found, invalid_state, fk_not_found,
    ERR_STALE_VEHICLE_VERSION,
)
from util import envelope, respond_list, body_arg, body_has, new_entity, bump, parse_iso
from rules import (
    TIERS, maybe_expire_vehicle, assert_scope_contained,
    assert_manufacturer_active, assert_agreement_good_standing,
    assert_vehicle_window_open, expire_vehicle_cascade, resolve_agreement_of_vehicle,
)


def vehicle_view(v):
    return {k: v[k] for k in ("id", "agreement_id", "vehicle_kind", "buyer_tiers",
                              "ceiling_cents", "taa_required", "effective_from", "effective_to",
                              "prc_accumulator_cents", "status",
                              "created_at", "updated_at", "version")}


def get_vehicle(vid):
    v = db.vehicles.get(vid)
    if v is None:
        raise not_found("vehicle not found")
    return v


@app.post("/vehicles")
def vehicles_create():
    agreement_id = body_arg("agreement_id")
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        raise fk_not_found("agreement_id not found")
    buyer_tiers = body_arg("buyer_tiers") or []
    if not isinstance(buyer_tiers, list) or not buyer_tiers or any(t not in TIERS for t in buyer_tiers):
        raise err("ERR_SCOPE_VIOLATION", "buyer_tiers must be a non-empty subset of the five tiers", 422)
    assert_scope_contained(buyer_tiers, agreement["scope_tiers"])
    effective_from = body_arg("effective_from")
    effective_to = body_arg("effective_to")
    v = new_entity(db, db.vehicles, {},
                   agreement_id=agreement_id,
                   vehicle_kind=body_arg("vehicle_kind"),
                   buyer_tiers=list(buyer_tiers),
                   ceiling_cents=body_arg("ceiling_cents"),
                   taa_required=body_arg("taa_required", True),
                   effective_from=effective_from, effective_to=effective_to,
                   prc_accumulator_cents=0, status="PENDING")
    v["_from"], v["_to"] = parse_iso(effective_from), parse_iso(effective_to)
    v["_cascade_suspended"] = False
    return envelope(vehicle_view(v), 201)


@app.get("/vehicles")
def vehicles_list():
    items = list(db.vehicles.values())
    aid = request.args.get("agreement_id")
    if aid is not None:
        items = [v for v in items if v["agreement_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return respond_list([vehicle_view(v) for v in items])


@app.get("/vehicles/<vid>")
def vehicles_get(vid):
    v = get_vehicle(vid)
    maybe_expire_vehicle(db, v)
    return envelope(vehicle_view(v), 200)


@app.patch("/vehicles/<vid>")
def vehicles_patch(vid):
    v = get_vehicle(vid)
    expected = body_arg("expected_vehicle_version")
    if expected != v["version"]:
        raise err(ERR_STALE_VEHICLE_VERSION, "expected_vehicle_version does not match current version", 412)
    if body_has("ceiling_cents"):
        v["ceiling_cents"] = body_arg("ceiling_cents")
    if body_has("effective_from"):
        v["effective_from"] = body_arg("effective_from")
        v["_from"] = parse_iso(v["effective_from"])
    if body_has("effective_to"):
        v["effective_to"] = body_arg("effective_to")
        v["_to"] = parse_iso(v["effective_to"])
    bump(v)
    return envelope(vehicle_view(v), 200)


@app.post("/vehicles/<vid>/authorize")
def vehicles_authorize(vid):
    v = get_vehicle(vid)
    if v["status"] != "PENDING":
        raise invalid_state("vehicle is not PENDING")
    agreement = resolve_agreement_of_vehicle(db, v)
    if agreement["status"] != "ACTIVE":
        raise invalid_state("agreement is not ACTIVE")
    assert_manufacturer_active(db, agreement)
    assert_agreement_good_standing(agreement)
    assert_scope_contained(v["buyer_tiers"], agreement["scope_tiers"])
    if not (v["_from"] is not None and v["_to"] is not None and v["_from"] < v["_to"]):
        raise err("ERR_OUTSIDE_VEHICLE_WINDOW", "effective_from must precede effective_to", 422)
    assert_vehicle_window_open(db, v)
    v["status"] = "AUTHORIZED"
    bump(v)
    return envelope(vehicle_view(v), 200)


@app.post("/vehicles/<vid>/suspend")
def vehicles_suspend(vid):
    v = get_vehicle(vid)
    maybe_expire_vehicle(db, v)
    if v["status"] != "AUTHORIZED":
        raise invalid_state("vehicle is not AUTHORIZED")
    v["status"] = "SUSPENDED"
    v["_cascade_suspended"] = False
    bump(v)
    return envelope(vehicle_view(v), 200)


@app.post("/vehicles/<vid>/reinstate")
def vehicles_reinstate(vid):
    v = get_vehicle(vid)
    if v["status"] != "SUSPENDED":
        raise invalid_state("vehicle is not SUSPENDED")
    agreement = resolve_agreement_of_vehicle(db, v)
    if agreement["status"] != "ACTIVE" or agreement["posture"] != "GOOD_STANDING":
        raise err("ERR_AGREEMENT_NOT_GOOD_STANDING",
                  "agreement must be ACTIVE and GOOD_STANDING to reinstate a vehicle", 422)
    v["status"] = "AUTHORIZED"
    v["_cascade_suspended"] = False
    bump(v)
    return envelope(vehicle_view(v), 200)


@app.post("/vehicles/<vid>/expire")
def vehicles_expire(vid):
    v = get_vehicle(vid)
    maybe_expire_vehicle(db, v)
    if v["status"] != "AUTHORIZED":
        raise invalid_state("vehicle is not AUTHORIZED")
    expire_vehicle_cascade(db, v)
    return envelope(vehicle_view(v), 200)


@app.get("/vehicles/<vid>/price-lists")
def vehicles_price_lists(vid):
    v = get_vehicle(vid)
    maybe_expire_vehicle(db, v)
    from routes.pricing import price_list_view
    items = [p for p in db.price_lists.values() if p["vehicle_id"] == vid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return respond_list([price_list_view(p) for p in items])


@app.get("/vehicles/<vid>/orders")
def vehicles_orders(vid):
    v = get_vehicle(vid)
    maybe_expire_vehicle(db, v)
    from routes.orders import order_view
    items = [o for o in db.orders.values() if o["vehicle_id"] == vid]
    bt = request.args.get("buyer_tier")
    if bt is not None:
        items = [o for o in items if o["buyer_tier"] == bt]
    cs = request.args.get("compliance_status")
    if cs is not None:
        items = [o for o in items if o["compliance_status"] == cs]
    bs = request.args.get("billing_status")
    if bs is not None:
        items = [o for o in items if o["billing_status"] == bs]
    return respond_list([order_view(o) for o in items])


@app.get("/vehicles/<vid>/teaming-scopes")
def vehicles_teaming_scopes(vid):
    v = get_vehicle(vid)
    maybe_expire_vehicle(db, v)
    from routes.teaming import teaming_scope_view
    items = [s for s in db.teaming_scopes.values() if s["vehicle_id"] == vid]
    return respond_list([teaming_scope_view(s) for s in items])
