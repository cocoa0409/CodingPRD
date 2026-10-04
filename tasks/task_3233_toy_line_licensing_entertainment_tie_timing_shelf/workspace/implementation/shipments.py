from flask import Blueprint, request
from auth import caller, require_role
from store import db, stamp_new, touch
from util import ApiErr, ok_obj, paged, not_found, bad_req, parse_iso, new_id, get_body, half_up_dec, now_iso
from decimal import Decimal

bp = Blueprint("shipments", __name__)

def sh_json(s):
    return {"id": s["id"], "commitment_id": s["commitment_id"],
            "planned_ship_date": s["planned_ship_date"], "units": s["units"],
            "street_date": s["street_date"], "sold_units": s["sold_units"],
            "sold_at": s["sold_at"], "status": s["status"],
            "penalty_cents": s["penalty_cents"], "penalty_status": s["penalty_status"],
            "created_at": s["created_at"], "updated_at": s["updated_at"],
            "version": s["version"]}

@bp.post("/shipments")
def create_shipment():
    require_role("BrandManager")
    b = get_body()
    for f in ("commitment_id", "planned_ship_date", "units"):
        if f not in b: bad_req(f"{f} required")
    c = db.commitments.get(b["commitment_id"])
    if not c: not_found("commitment not found")
    parse_iso(b["planned_ship_date"])
    if not isinstance(b["units"], int) or b["units"] < 1:
        bad_req("units must be >= 1")
    sku = db.skus.get(c["sku_id"])
    line = db.lines.get(sku["toy_line_id"]) if sku else None
    sd = line["target_street_date"] if line else None
    s = {"id": new_id(), "commitment_id": c["id"],
         "planned_ship_date": b["planned_ship_date"], "units": b["units"],
         "street_date": sd, "_sd_dt": line["_tsd_dt"] if line else None,
         "sold_units": 0, "sold_at": None, "_sold_at_dt": None,
         "status": "PLANNED", "penalty_cents": 0, "penalty_status": "NONE"}
    stamp_new(s)
    db.shipments[s["id"]] = s
    return ok_obj(sh_json(s), 201)

@bp.get("/shipments/<sid>")
def get_shipment(sid):
    caller()
    s = db.shipments.get(sid)
    if not s: not_found("shipment not found")
    return ok_obj(sh_json(s))

@bp.get("/shipments")
def list_shipments():
    caller()
    items = list(db.shipments.values())
    for q in ("commitment_id", "status"):
        v = request.args.get(q)
        if v is not None:
            items = [s for s in items if s[q] == v]
    return paged([sh_json(s) for s in items])

def shipment_retailer(sh):
    c = db.commitments.get(sh["commitment_id"])
    rv = db.reviews.get(c["line_review_id"]) if c else None
    return db.retailers.get(rv["retailer_id"]) if rv else None

@bp.post("/shipments/<sid>/record_sale")
def record_sale(sid):
    call = require_role("RetailerOps")
    s = db.shipments.get(sid)
    if not s: not_found("shipment not found")
    ret = shipment_retailer(s)
    if not ret or call["id"] != ret["id"]:
        raise ApiErr("ERR_UNAUTHORIZED", 403, "not your retailer's shipment")
    if s["status"] not in ("PLANNED", "SOLD"):
        raise ApiErr("ERR_INVALID_STATE", 409, "shipment not sellable")
    b = get_body()
    us = b.get("units_sold")
    if not isinstance(us, int) or us < 1:
        bad_req("units_sold must be >= 1")
    if s["status"] == "SOLD" and s["sold_units"] + us > s["units"]:
        raise ApiErr("ERR_SHIPMENT_OVERSOLD", 422, "oversold")
    if s["status"] == "PLANNED":
        s["sold_units"] = us
        s["status"] = "SOLD"
    else:
        s["sold_units"] += us
    s["sold_at"] = now_iso(db.clock)
    s["_sold_at_dt"] = db.clock
    # embargo penalty
    if s["_sd_dt"] is not None and db.clock < s["_sd_dt"]:
        c = db.commitments.get(s["commitment_id"])
        base = s["sold_units"] * c["unit_price_cents"]
        rate = Decimal("0.25") if ret["violation_count"] >= 2 else Decimal("0.10")
        penalty = half_up_dec(Decimal(base) * rate)
        # if a previous OPEN penalty exists on this shipment, it is re-assessed:
        # per PRD the penalty is (re)assessed on cumulative sold_units. The ledger
        # conservation invariant counts OPEN penalties; a re-assessment replaces the
        # prior penalty amount, so credit back the old debit first.
        if s["penalty_status"] == "OPEN":
            ret["credit_balance_cents"] += s["penalty_cents"]
        s["penalty_cents"] = penalty
        s["penalty_status"] = "OPEN"
        ret["credit_balance_cents"] -= penalty
        ret["violation_count"] += 1
    touch(s)
    return ok_obj(sh_json(s))

@bp.post("/shipments/<sid>/waive_penalty")
def waive_penalty(sid):
    require_role("BrandManager")
    s = db.shipments.get(sid)
    if not s: not_found("shipment not found")
    if s["penalty_status"] != "OPEN":
        raise ApiErr("ERR_INVALID_STATE", 409, "no OPEN penalty")
    ret = shipment_retailer(s)
    if ret:
        ret["credit_balance_cents"] += s["penalty_cents"]
    s["penalty_status"] = "WAIVED"
    touch(s)
    return ok_obj(sh_json(s))
