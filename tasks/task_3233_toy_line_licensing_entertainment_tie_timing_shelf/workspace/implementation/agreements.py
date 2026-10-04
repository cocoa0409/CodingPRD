from flask import Blueprint, request
from auth import caller, require_role
from store import db, stamp_new, touch
from util import (ApiErr, ok_obj, paged, not_found, bad_req, parse_iso, new_id,
                  get_body, round_half_up, half_up_dec)
from decimal import Decimal

bp = Blueprint("agreements", __name__)

PENDING = ("pending_royalty_rate_pct", "pending_advance_guarantee_cents", "pending_end_date")

def ag_json(a):
    return {"id": a["id"], "property_id": a["property_id"], "territory": a["territory"],
            "royalty_rate_pct": a["royalty_rate_pct"],
            "advance_guarantee_cents": a["advance_guarantee_cents"],
            "annual_minimum_guarantee_cents": a["annual_minimum_guarantee_cents"],
            "start_date": a["start_date"], "end_date": a["end_date"],
            "approval_rights_required": a["approval_rights_required"],
            "status": a["status"],
            "pending_royalty_rate_pct": a["pending_royalty_rate_pct"],
            "pending_advance_guarantee_cents": a["pending_advance_guarantee_cents"],
            "pending_end_date": a["pending_end_date"],
            "royalties_earned_cents": a["royalties_earned_cents"],
            "recouped_cents": a["recouped_cents"],
            "guarantee_topups_cents": a["guarantee_topups_cents"],
            "quarters_closed": a["quarters_closed"],
            "created_at": a["created_at"], "updated_at": a["updated_at"],
            "version": a["version"]}

def quarter_bounds(a, qi):
    # quarter_index qi is 0-based; quarters relative to start_date, 3 months each
    from datetime import timedelta
    start = a["_start_dt"]
    def add_months(dt, m):
        y = dt.year + (dt.month - 1 + m) // 12
        mo = (dt.month - 1 + m) % 12 + 1
        return dt.replace(year=y, month=mo)
    return add_months(start, qi * 3), add_months(start, qi * 3 + 3)

def lines_for_agreement(aid):
    return [l for l in db.lines.values() if l.get("license_agreement_id") == aid]

def sku_ids_for_agreement(aid):
    lids = {l["id"] for l in lines_for_agreement(aid)}
    return {s["id"] for s in db.skus.values() if s["toy_line_id"] in lids}

def quarter_gross(a, lo, hi, provisional=False):
    skus = sku_ids_for_agreement(a["id"])
    total = 0
    for sh in db.shipments.values():
        c = db.commitments.get(sh["commitment_id"])
        if not c or c["sku_id"] not in skus:
            continue
        if sh["status"] == "SOLD" and sh.get("_sold_at_dt") is not None and lo <= sh["_sold_at_dt"] < hi:
            total += sh["sold_units"] * c["unit_price_cents"]
        elif provisional and sh["status"] == "PLANNED":
            total += sh["units"] * c["unit_price_cents"]
    return total

@bp.post("/license-agreements")
def create_agreement():
    require_role("BrandManager")
    b = get_body()
    req = ("property_id", "territory", "royalty_rate_pct", "advance_guarantee_cents",
           "annual_minimum_guarantee_cents", "start_date", "end_date", "approval_rights_required")
    for f in req:
        if f not in b: bad_req(f"{f} required")
    p = db.properties.get(b["property_id"])
    if not p: not_found("property not found")
    if not isinstance(b["territory"], str): bad_req("territory required")
    if not isinstance(b["royalty_rate_pct"], (int, float)): bad_req("royalty_rate_pct must be number")
    for f in ("advance_guarantee_cents", "annual_minimum_guarantee_cents"):
        if not isinstance(b[f], int) or b[f] < 0: bad_req(f"{f} must be non-negative int")
    if not isinstance(b["approval_rights_required"], bool): bad_req("approval_rights_required must be bool")
    sd = parse_iso(b["start_date"]); ed = parse_iso(b["end_date"])
    a = {"id": new_id(), "property_id": p["id"], "territory": b["territory"],
         "royalty_rate_pct": b["royalty_rate_pct"],
         "advance_guarantee_cents": b["advance_guarantee_cents"],
         "annual_minimum_guarantee_cents": b["annual_minimum_guarantee_cents"],
         "start_date": b["start_date"], "end_date": b["end_date"],
         "approval_rights_required": b["approval_rights_required"],
         "status": "NEGOTIATION",
         "pending_royalty_rate_pct": None, "pending_advance_guarantee_cents": None,
         "pending_end_date": None,
         "royalties_earned_cents": 0, "recouped_cents": 0,
         "guarantee_topups_cents": 0, "quarters_closed": 0,
         "_start_dt": sd, "_end_dt": ed, "_earned_hist": []}
    stamp_new(a)
    db.agreements[a["id"]] = a
    return ok_obj(ag_json(a), 201)

@bp.get("/license-agreements/<aid>")
def get_agreement(aid):
    caller()
    a = db.agreements.get(aid)
    if not a: not_found("agreement not found")
    return ok_obj(ag_json(a))

@bp.get("/license-agreements")
def list_agreements():
    caller()
    items = list(db.agreements.values())
    pid = request.args.get("property_id")
    if pid is not None:
        items = [a for a in items if a["property_id"] == pid]
    return paged([ag_json(a) for a in items])

@bp.post("/license-agreements/<aid>/activate")
def activate(aid):
    c = require_role("StudioRep", "BrandManager")
    a = db.agreements.get(aid)
    if not a: not_found("agreement not found")
    if a["status"] != "NEGOTIATION":
        raise ApiErr("ERR_INVALID_STATE", 409, "agreement not NEGOTIATION")
    if a["_start_dt"] > a["_end_dt"]:
        raise ApiErr("ERR_INVALID_STATE", 409, "start_date after end_date")
    if a["approval_rights_required"] and c["role"] != "StudioRep":
        raise ApiErr("ERR_UNAUTHORIZED", 403, "StudioRep required")
    b = get_body()
    if "expected_license_agreement_version" in b:
        if b["expected_license_agreement_version"] != a["version"]:
            raise ApiErr("ERR_STALE_VERSION", 412, "stale version")
    a["status"] = "ACTIVE"
    touch(a)
    return ok_obj(ag_json(a))

@bp.post("/license-agreements/<aid>/amend")
def amend(aid):
    require_role("BrandManager")
    a = db.agreements.get(aid)
    if not a: not_found("agreement not found")
    if a["status"] != "ACTIVE":
        raise ApiErr("ERR_INVALID_STATE", 409, "agreement not ACTIVE")
    b = get_body()
    for f in ("royalty_rate_pct", "advance_guarantee_cents", "end_date"):
        if f not in b: bad_req(f"{f} required")
    parse_iso(b["end_date"])
    a["pending_royalty_rate_pct"] = b["royalty_rate_pct"]
    a["pending_advance_guarantee_cents"] = b["advance_guarantee_cents"]
    a["pending_end_date"] = b["end_date"]
    a["status"] = "AMENDMENT_PENDING"
    touch(a)
    return ok_obj(ag_json(a))

@bp.post("/license-agreements/<aid>/amendments/approve")
def approve_amendment(aid):
    require_role("StudioRep")
    a = db.agreements.get(aid)
    if not a: not_found("agreement not found")
    if a["status"] != "AMENDMENT_PENDING":
        raise ApiErr("ERR_INVALID_STATE", 409, "no pending amendment")
    a["royalty_rate_pct"] = a["pending_royalty_rate_pct"]
    a["advance_guarantee_cents"] = a["pending_advance_guarantee_cents"]
    a["end_date"] = a["pending_end_date"]
    a["_end_dt"] = parse_iso(a["pending_end_date"])
    for f in PENDING: a[f] = None
    a["status"] = "ACTIVE"
    touch(a)
    return ok_obj(ag_json(a))

@bp.post("/license-agreements/<aid>/amendments/reject")
def reject_amendment(aid):
    require_role("StudioRep")
    a = db.agreements.get(aid)
    if not a: not_found("agreement not found")
    if a["status"] != "AMENDMENT_PENDING":
        raise ApiErr("ERR_INVALID_STATE", 409, "no pending amendment")
    for f in PENDING: a[f] = None
    a["status"] = "ACTIVE"
    touch(a)
    return ok_obj(ag_json(a))

@bp.post("/license-agreements/<aid>/close_quarter")
def close_quarter(aid):
    require_role("BrandManager")
    a = db.agreements.get(aid)
    if not a: not_found("agreement not found")
    b = get_body()
    qi = b.get("quarter_index")
    if not isinstance(qi, int) or qi < 0: bad_req("quarter_index must be non-negative int")
    lo, hi = quarter_bounds(a, qi)
    gross = quarter_gross(a, lo, hi, provisional=False)
    earned = half_up_dec(Decimal(str(gross)) * Decimal(str(a["royalty_rate_pct"])))
    recoup = min(earned, max(0, a["advance_guarantee_cents"] - a["recouped_cents"]))
    topup = 0
    if (a["quarters_closed"] + 1) % 4 == 0:
        year_min = a["annual_minimum_guarantee_cents"]
        earned_year = earned + sum(a["_earned_hist"][-3:])
        if earned_year < year_min:
            topup = year_min - earned_year
    a["royalties_earned_cents"] += earned + topup
    a["recouped_cents"] += recoup
    a["guarantee_topups_cents"] += topup
    a["quarters_closed"] += 1
    a["_earned_hist"].append(earned)
    touch(a)
    return ok_obj(ag_json(a))

@bp.get("/license-agreements/<aid>/royalty_projection")
def royalty_projection(aid):
    require_role("BrandManager", "StudioRep")
    a = db.agreements.get(aid)
    if not a: not_found("agreement not found")
    qi = a["quarters_closed"]
    lo, hi = quarter_bounds(a, qi)
    gross = quarter_gross(a, lo, hi, provisional=True)
    rate = a["pending_royalty_rate_pct"] if a["status"] == "AMENDMENT_PENDING" else a["royalty_rate_pct"]
    earned = half_up_dec(Decimal(str(gross)) * Decimal(str(rate)))
    adv = a["pending_advance_guarantee_cents"] if a["status"] == "AMENDMENT_PENDING" else a["advance_guarantee_cents"]
    recoup = min(earned, max(0, adv - a["recouped_cents"]))
    return ok_obj({"projected_earned_cents": earned,
                   "projected_recoup_cents": recoup,
                   "projected_payable_cents": earned - recoup})
