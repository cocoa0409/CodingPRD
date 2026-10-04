from flask import Blueprint, request
from auth import caller, require_role
from store import db, stamp_new, touch, review_lifecycle
from util import ApiErr, ok_obj, paged, not_found, bad_req, parse_iso, new_id, get_body

bp = Blueprint("retail", __name__)

def ret_json(r):
    return {"id": r["id"], "name": r["name"], "region": r["region"],
            "credit_balance_cents": r["credit_balance_cents"],
            "violation_count": r["violation_count"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
            "version": r["version"]}

@bp.post("/retailers")
def create_retailer():
    require_role("PlatformAdmin")
    b = get_body()
    for f in ("name", "region"):
        if f not in b: bad_req(f"{f} required")
    if not isinstance(b["name"], str) or not b["name"]: bad_req("name required")
    if not isinstance(b["region"], str): bad_req("region required")
    r = {"id": new_id(), "name": b["name"], "region": b["region"],
         "credit_balance_cents": 0, "violation_count": 0}
    stamp_new(r)
    db.retailers[r["id"]] = r
    return ok_obj(ret_json(r), 201)

@bp.get("/retailers/<rid>")
def get_retailer(rid):
    caller()
    r = db.retailers.get(rid)
    if not r: not_found("retailer not found")
    return ok_obj(ret_json(r))

def rev_json(rv):
    return {"id": rv["id"], "retailer_id": rv["retailer_id"],
            "window_start": rv["window_start"], "window_end": rv["window_end"],
            "commitment_deadline": rv["commitment_deadline"],
            "shelf_slots_total": rv["shelf_slots_total"],
            "shelf_slots_used": rv["shelf_slots_used"],
            "status": rv["status"], "lifecycle": review_lifecycle(rv),
            "created_at": rv["created_at"], "updated_at": rv["updated_at"],
            "version": rv["version"]}

@bp.post("/line-reviews")
def create_review():
    c = require_role("RetailerOps")
    b = get_body()
    req = ("retailer_id", "window_start", "window_end", "commitment_deadline", "shelf_slots_total")
    for f in req:
        if f not in b: bad_req(f"{f} required")
    r = db.retailers.get(b["retailer_id"])
    if not r: not_found("retailer not found")
    if c["id"] != r["id"]:
        raise ApiErr("ERR_UNAUTHORIZED", 403, "RetailerOps may schedule only for own retailer")
    ws = parse_iso(b["window_start"]); we = parse_iso(b["window_end"])
    cd = parse_iso(b["commitment_deadline"])
    if not isinstance(b["shelf_slots_total"], int) or b["shelf_slots_total"] < 0:
        bad_req("shelf_slots_total must be non-negative int")
    if not (ws <= cd <= we):
        raise ApiErr("ERR_CONSTRAINT_VIOLATION", 422, "window ordering violated")
    for other in db.reviews.values():
        if other["retailer_id"] == r["id"]:
            if ws < other["_we_dt"] and other["_ws_dt"] < we:
                raise ApiErr("ERR_REVIEW_WINDOW_OVERLAP", 409, "window overlaps existing review")
    rv = {"id": new_id(), "retailer_id": r["id"],
          "window_start": b["window_start"], "window_end": b["window_end"],
          "commitment_deadline": b["commitment_deadline"],
          "shelf_slots_total": b["shelf_slots_total"], "shelf_slots_used": 0,
          "status": "PENDING_APPROVAL",
          "_ws_dt": ws, "_we_dt": we, "_cd_dt": cd}
    stamp_new(rv)
    db.reviews[rv["id"]] = rv
    return ok_obj(rev_json(rv), 201)

@bp.post("/line-reviews/<rid>/approve")
def approve_review(rid):
    require_role("BrandManager")
    rv = db.reviews.get(rid)
    if not rv: not_found("line review not found")
    if rv["status"] != "PENDING_APPROVAL":
        raise ApiErr("ERR_INVALID_STATE", 409, "review not PENDING_APPROVAL")
    rv["status"] = "CONFIRMED"
    touch(rv)
    return ok_obj(rev_json(rv))

@bp.get("/line-reviews/<rid>")
def get_review(rid):
    caller()
    rv = db.reviews.get(rid)
    if not rv: not_found("line review not found")
    return ok_obj(rev_json(rv))

@bp.get("/line-reviews")
def list_reviews():
    caller()
    items = list(db.reviews.values())
    rid = request.args.get("retailer_id")
    if rid is not None:
        items = [r for r in items if r["retailer_id"] == rid]
    return paged([rev_json(r) for r in items])
