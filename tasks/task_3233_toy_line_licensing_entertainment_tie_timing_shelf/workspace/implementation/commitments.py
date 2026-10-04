from flask import Blueprint, request
from auth import caller, require_role
from store import db, stamp_new, touch, review_lifecycle, recompute_shelf
from util import ApiErr, ok_obj, paged, not_found, bad_req, parse_iso, new_id, get_body, now_iso

bp = Blueprint("commitments", __name__)

def com_json(c):
    return {"id": c["id"], "line_review_id": c["line_review_id"], "sku_id": c["sku_id"],
            "committed_units": c["committed_units"], "unit_price_cents": c["unit_price_cents"],
            "shelf_slots": c["shelf_slots"], "status": c["status"],
            "created_at": c["created_at"], "updated_at": c["updated_at"],
            "version": c["version"]}

@bp.post("/assortment-commitments")
def create_commitment():
    require_role("BrandManager")
    b = get_body()
    req = ("line_review_id", "sku_id", "committed_units", "unit_price_cents", "shelf_slots")
    for f in req:
        if f not in b: bad_req(f"{f} required")
    rv = db.reviews.get(b["line_review_id"])
    if not rv: not_found("line review not found")
    sku = db.skus.get(b["sku_id"])
    if not sku: not_found("sku not found")
    if review_lifecycle(rv) != "OPEN":
        raise ApiErr("ERR_CONSTRAINT_VIOLATION", 422, "review not OPEN")
    if not isinstance(b["committed_units"], int) or b["committed_units"] < 1:
        bad_req("committed_units must be >= 1")
    if not isinstance(b["unit_price_cents"], int) or b["unit_price_cents"] < 0:
        bad_req("unit_price_cents must be non-negative int")
    if not isinstance(b["shelf_slots"], int) or b["shelf_slots"] < 1:
        bad_req("shelf_slots must be >= 1")
    if rv["shelf_slots_used"] + b["shelf_slots"] > rv["shelf_slots_total"]:
        raise ApiErr("ERR_SHELF_OVERFLOW", 422, "shelf capacity exceeded")
    c = {"id": new_id(), "line_review_id": rv["id"], "sku_id": sku["id"],
         "committed_units": b["committed_units"], "unit_price_cents": b["unit_price_cents"],
         "shelf_slots": b["shelf_slots"], "status": "COMMITTED"}
    stamp_new(c)
    db.commitments[c["id"]] = c
    recompute_shelf(rv["id"])
    return ok_obj(com_json(c), 201)

@bp.get("/assortment-commitments/<cid>")
def get_commitment(cid):
    caller()
    c = db.commitments.get(cid)
    if not c: not_found("commitment not found")
    return ok_obj(com_json(c))

@bp.get("/assortment-commitments")
def list_commitments():
    caller()
    items = list(db.commitments.values())
    for q in ("line_review_id", "sku_id", "status"):
        v = request.args.get(q)
        if v is not None:
            items = [c for c in items if c[q] == v]
    return paged([com_json(c) for c in items])

@bp.post("/assortment-commitments/<cid>/cancel")
def cancel_commitment(cid):
    require_role("BrandManager")
    c = db.commitments.get(cid)
    if not c: not_found("commitment not found")
    rv = db.reviews.get(c["line_review_id"])
    if c["status"] not in ("COMMITTED", "AT_RISK"):
        raise ApiErr("ERR_INVALID_STATE", 409, "commitment not cancellable")
    if review_lifecycle(rv) != "OPEN":
        raise ApiErr("ERR_INVALID_STATE", 409, "review not OPEN")
    c["status"] = "CANCELLED"
    touch(c)
    recompute_shelf(rv["id"])
    return ok_obj(com_json(c))

@bp.post("/assortment-commitments/<cid>/reinstate")
def reinstate_commitment(cid):
    require_role("BrandManager")
    c = db.commitments.get(cid)
    if not c: not_found("commitment not found")
    rv = db.reviews.get(c["line_review_id"])
    if c["status"] != "AT_RISK":
        raise ApiErr("ERR_INVALID_STATE", 409, "commitment not AT_RISK")
    if review_lifecycle(rv) != "OPEN":
        raise ApiErr("ERR_INVALID_STATE", 409, "review not OPEN")
    c["status"] = "COMMITTED"
    touch(c)
    return ok_obj(com_json(c))
