"""ManufacturerAgreement surface."""
from flask import request

import db
from server_core import app
from errors import (
    err, not_found, invalid_state, fk_not_found,
    ERR_MANUFACTURER_INACTIVE, ERR_SB_GOAL_NOT_MET,
    ERR_STALE_AGREEMENT_VERSION, ERR_UNIQUENESS_VIOLATION,
)
from util import (
    envelope, respond_list, body_arg, body_has, new_entity, bump, parse_iso,
)
from rules import (
    TIERS, recompute_posture, recompute_sb_goal,
    cascade_suspend_agreement, cascade_reinstate_agreement, cascade_terminate_agreement,
)
from routes.vehicles import vehicle_view
from routes.teaming import teaming_view
from routes.reporting import sales_report_view, audit_view


def agreement_view(a):
    return {k: a[k] for k in ("id", "manufacturer_id", "scope_tiers", "mfc_discount_pct",
                              "small_business_goal_pct", "product_scope", "term_start", "term_end",
                              "dispute_credit_cents", "posture", "status",
                              "created_at", "updated_at", "version")}


def get_agreement(aid):
    a = db.agreements.get(aid)
    if a is None:
        raise not_found("agreement not found")
    return a


@app.post("/agreements")
def agreements_create():
    manufacturer_id = body_arg("manufacturer_id")
    manufacturer = db.manufacturers.get(manufacturer_id)
    if manufacturer is None:
        raise fk_not_found("manufacturer_id not found")
    scope_tiers = body_arg("scope_tiers") or []
    if not isinstance(scope_tiers, list) or not scope_tiers or any(t not in TIERS for t in scope_tiers):
        raise err("ERR_SCOPE_VIOLATION", "scope_tiers must be a non-empty subset of the five buyer tiers", 422)
    mfc = body_arg("mfc_discount_pct")
    sb = body_arg("small_business_goal_pct")
    product_scope = body_arg("product_scope") or []
    term_start = body_arg("term_start")
    term_end = body_arg("term_end")
    ts, te = parse_iso(term_start), parse_iso(term_end)
    a = new_entity(db, db.agreements, {},
                   manufacturer_id=manufacturer_id,
                   scope_tiers=list(scope_tiers),
                   mfc_discount_pct=mfc,
                   small_business_goal_pct=sb,
                   product_scope=list(product_scope),
                   term_start=term_start, term_end=term_end,
                   dispute_credit_cents=0, posture="GOOD_STANDING", status="DRAFT")
    a["_ts"], a["_te"] = ts, te
    return envelope(agreement_view(a), 201)


@app.get("/agreements")
def agreements_list():
    items = list(db.agreements.values())
    mid = request.args.get("manufacturer_id")
    if mid is not None:
        items = [a for a in items if a["manufacturer_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return respond_list([agreement_view(a) for a in items])


@app.get("/agreements/<aid>")
def agreements_get(aid):
    return envelope(agreement_view(get_agreement(aid)), 200)


@app.patch("/agreements/<aid>")
def agreements_patch(aid):
    a = get_agreement(aid)
    expected = body_arg("expected_agreement_version")
    if expected != a["version"]:
        raise err(ERR_STALE_AGREEMENT_VERSION, "expected_agreement_version does not match current version", 412)
    if body_has("mfc_discount_pct"):
        a["mfc_discount_pct"] = body_arg("mfc_discount_pct")
    if body_has("scope_tiers"):
        a["scope_tiers"] = body_arg("scope_tiers")
    if body_has("product_scope"):
        a["product_scope"] = body_arg("product_scope")
    if body_has("small_business_goal_pct"):
        a["small_business_goal_pct"] = body_arg("small_business_goal_pct")
    bump(a)
    return envelope(agreement_view(a), 200)


@app.post("/agreements/<aid>/activate")
def agreements_activate(aid):
    a = get_agreement(aid)
    if a["status"] != "DRAFT":
        raise invalid_state("agreement is not DRAFT")
    if not (a["_ts"] is not None and a["_te"] is not None and a["_ts"] < a["_te"]):
        raise err("ERR_INVALID_STATE", "term_start must precede term_end", 409)
    if not a["scope_tiers"]:
        raise err("ERR_INVALID_STATE", "scope_tiers must be non-empty", 409)
    manufacturer = db.manufacturers.get(a["manufacturer_id"])
    if manufacturer is None or manufacturer["status"] != "ACTIVE":
        raise err(ERR_MANUFACTURER_INACTIVE, "manufacturer is not ACTIVE", 422)
    for other in db.agreements.values():
        if other["id"] != a["id"] and other["manufacturer_id"] == a["manufacturer_id"] and other["status"] == "ACTIVE":
            raise err(ERR_UNIQUENESS_VIOLATION, "another agreement for this manufacturer is already ACTIVE", 409)
    a["status"] = "ACTIVE"
    recompute_posture(a)
    bump(a)
    return envelope(agreement_view(a), 200)


@app.post("/agreements/<aid>/suspend")
def agreements_suspend(aid):
    a = get_agreement(aid)
    if a["status"] != "ACTIVE":
        raise invalid_state("agreement is not ACTIVE")
    a["status"] = "SUSPENDED"
    recompute_posture(a)
    cascade_suspend_agreement(db, a)
    bump(a)
    return envelope(agreement_view(a), 200)


@app.post("/agreements/<aid>/reinstate")
def agreements_reinstate(aid):
    a = get_agreement(aid)
    if a["status"] != "SUSPENDED":
        raise invalid_state("agreement is not SUSPENDED")
    manufacturer = db.manufacturers.get(a["manufacturer_id"])
    if manufacturer is None or manufacturer["status"] != "ACTIVE":
        raise err(ERR_MANUFACTURER_INACTIVE, "manufacturer is not ACTIVE", 422)
    if int(a["dispute_credit_cents"]) < -100000:
        raise err("ERR_AGREEMENT_NOT_GOOD_STANDING", "dispute ledger still in ON_HOLD band", 422)
    a["status"] = "ACTIVE"
    recompute_posture(a)
    cascade_reinstate_agreement(db, a)
    bump(a)
    return envelope(agreement_view(a), 200)


@app.post("/agreements/<aid>/terminate")
def agreements_terminate(aid):
    a = get_agreement(aid)
    if a["status"] != "ACTIVE":
        raise invalid_state("agreement is not ACTIVE")
    reports = [r for r in db.sales_reports.values() if r["agreement_id"] == a["id"]]
    for r in reports:
        if r["status"] != "FINALIZED":
            recompute_sb_goal(db, r, a)
            raise err(ERR_SB_GOAL_NOT_MET, "every sales report must be FINALIZED before termination", 422)
        if not r["sb_goal_met"]:
            raise err(ERR_SB_GOAL_NOT_MET, "a finalized sales report has sb_goal_met == false", 422)
    a["status"] = "TERMINATED"
    recompute_posture(a)
    cascade_terminate_agreement(db, a)
    bump(a)
    return envelope(agreement_view(a), 200)


@app.get("/agreements/<aid>/vehicles")
def agreements_vehicles(aid):
    get_agreement(aid)
    items = [v for v in db.vehicles.values() if v["agreement_id"] == aid]
    return respond_list([vehicle_view(v) for v in items])


@app.get("/agreements/<aid>/teaming")
def agreements_teaming(aid):
    get_agreement(aid)
    items = [t for t in db.teaming.values() if t["agreement_id"] == aid]
    return respond_list([teaming_view(t) for t in items])


@app.get("/agreements/<aid>/sales-reports")
def agreements_sales_reports(aid):
    get_agreement(aid)
    items = [r for r in db.sales_reports.values() if r["agreement_id"] == aid]
    period = request.args.get("period_label")
    if period is not None:
        items = [r for r in items if r["period_label"] == period]
    return respond_list([sales_report_view(r) for r in items])


@app.get("/agreements/<aid>/audits")
def agreements_audits(aid):
    get_agreement(aid)
    items = [x for x in db.audits.values() if x["agreement_id"] == aid]
    return respond_list([audit_view(x) for x in items])
