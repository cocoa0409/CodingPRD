"""TeamingArrangement + TeamingScope surface."""
from flask import request

import db
from server_core import app
from errors import err, not_found, invalid_state, fk_not_found, ERR_SCOPE_VIOLATION
from util import envelope, respond_list, body_arg, new_entity, bump, parse_iso
from rules import (
    assert_agreement_good_standing, assert_vehicle_authorized, sku_matches_scope,
)


def teaming_view(t):
    return {k: t[k] for k in ("id", "agreement_id", "integrator_name", "small_business",
                              "revenue_share_pct", "window_start", "window_end", "status",
                              "created_at", "updated_at", "version")}


def teaming_scope_view(s):
    return {k: s[k] for k in ("id", "teaming_id", "vehicle_id", "sku_prefixes", "created_at")}


def get_teaming(tid):
    t = db.teaming.get(tid)
    if t is None:
        raise not_found("teaming arrangement not found")
    return t


def assert_scopes_within_product_scope(scopes, product_scope):
    for sc in scopes:
        for prefix in (sc.get("sku_prefixes") or []):
            if prefix not in set(product_scope or []):
                raise err(ERR_SCOPE_VIOLATION,
                          "teaming scope sku_prefixes must be a subset of the agreement product_scope", 422)


@app.post("/teaming")
def teaming_create():
    agreement_id = body_arg("agreement_id")
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        raise fk_not_found("agreement_id not found")
    scopes = body_arg("scopes") or []
    for sc in scopes:
        vid = sc.get("vehicle_id")
        if vid not in db.vehicles:
            raise fk_not_found("scope vehicle_id not found")
        if not sc.get("sku_prefixes"):
            raise err(ERR_SCOPE_VIOLATION, "teaming scope sku_prefixes must be non-empty", 422)
    assert_scopes_within_product_scope(scopes, agreement["product_scope"])
    t = new_entity(db, db.teaming, {},
                   agreement_id=agreement_id,
                   integrator_name=body_arg("integrator_name"),
                   small_business=body_arg("small_business"),
                   revenue_share_pct=body_arg("revenue_share_pct"),
                   window_start=body_arg("window_start"),
                   window_end=body_arg("window_end"),
                   status="PROPOSED")
    t["_ws"], t["_we"] = parse_iso(t["window_start"]), parse_iso(t["window_end"])
    for sc in scopes:
        new_entity(db, db.teaming_scopes, {}, common=False,
                   teaming_id=t["id"],
                   vehicle_id=sc.get("vehicle_id"),
                   sku_prefixes=list(sc.get("sku_prefixes") or []))
    return envelope(teaming_view(t), 201)


@app.get("/teaming")
def teaming_list():
    items = list(db.teaming.values())
    aid = request.args.get("agreement_id")
    if aid is not None:
        items = [t for t in items if t["agreement_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return respond_list([teaming_view(t) for t in items])


@app.get("/teaming/<tid>")
def teaming_get(tid):
    return envelope(teaming_view(get_teaming(tid)), 200)


@app.get("/teaming/<tid>/scopes")
def teaming_scopes(tid):
    get_teaming(tid)
    items = [s for s in db.teaming_scopes.values() if s["teaming_id"] == tid]
    return respond_list([teaming_scope_view(s) for s in items])


@app.get("/teaming/<tid>/orders")
def teaming_orders(tid):
    get_teaming(tid)
    from routes.orders import order_view
    items = [o for o in db.orders.values() if o.get("teaming_id") == tid]
    return respond_list([order_view(o) for o in items])


@app.post("/teaming/<tid>/approve")
def teaming_approve(tid):
    t = get_teaming(tid)
    if t["status"] != "PROPOSED":
        raise invalid_state("teaming arrangement is not PROPOSED")
    agreement = db.agreements[t["agreement_id"]]
    if agreement["status"] != "ACTIVE":
        raise invalid_state("agreement is not ACTIVE")
    assert_agreement_good_standing(agreement)
    for s in db.teaming_scopes.values():
        if s["teaming_id"] == tid:
            assert_vehicle_authorized(db, db.vehicles[s["vehicle_id"]])
            for prefix in (s["sku_prefixes"] or []):
                if prefix not in set(agreement["product_scope"] or []):
                    raise err(ERR_SCOPE_VIOLATION,
                              "teaming scope sku_prefixes must remain within the agreement product_scope", 422)
    t["status"] = "APPROVED"
    bump(t)
    return envelope(teaming_view(t), 200)


@app.post("/teaming/<tid>/suspend")
def teaming_suspend(tid):
    t = get_teaming(tid)
    if t["status"] != "APPROVED":
        raise invalid_state("teaming arrangement is not APPROVED")
    t["status"] = "SUSPENDED"
    bump(t)
    return envelope(teaming_view(t), 200)


@app.post("/teaming/<tid>/reinstate")
def teaming_reinstate(tid):
    t = get_teaming(tid)
    if t["status"] != "SUSPENDED":
        raise invalid_state("teaming arrangement is not SUSPENDED")
    agreement = db.agreements[t["agreement_id"]]
    if agreement["status"] != "ACTIVE" or agreement["posture"] != "GOOD_STANDING":
        raise err("ERR_AGREEMENT_NOT_GOOD_STANDING",
                  "agreement must be ACTIVE and GOOD_STANDING to reinstate teaming", 422)
    t["status"] = "APPROVED"
    bump(t)
    return envelope(teaming_view(t), 200)


@app.post("/teaming/<tid>/terminate")
def teaming_terminate(tid):
    t = get_teaming(tid)
    if t["status"] != "APPROVED":
        raise invalid_state("teaming arrangement is not APPROVED")
    t["status"] = "TERMINATED"
    bump(t)
    return envelope(teaming_view(t), 200)
