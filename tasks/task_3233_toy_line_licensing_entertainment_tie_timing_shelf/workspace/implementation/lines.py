from flask import Blueprint, request
from auth import caller, require_role
from store import db, stamp_new, touch, property_lifecycle, recompute_shelf
from util import (ApiErr, ok_obj, paged, not_found, bad_req, parse_iso, new_id,
                  get_body, half_up_dec)
from decimal import Decimal

bp = Blueprint("lines", __name__)

def line_json(l):
    return {"id": l["id"], "name": l["name"], "brand_kind": l["brand_kind"],
            "property_id": l["property_id"], "license_agreement_id": l["license_agreement_id"],
            "target_street_date": l["target_street_date"],
            "target_street_date_input": l["target_street_date_input"],
            "status": l["status"], "closeout_markdown_pct": l["closeout_markdown_pct"],
            "closeout_recovery_cents": l["closeout_recovery_cents"],
            "created_at": l["created_at"], "updated_at": l["updated_at"],
            "version": l["version"]}

def confidential_gate_for_prop(prop):
    if property_lifecycle(prop) == "CONFIDENTIAL":
        raise ApiErr("ERR_CONFIDENTIALITY_BREACH", 422, "property is CONFIDENTIAL")

@bp.post("/toy-lines")
def create_line():
    require_role("BrandManager")
    b = get_body()
    for f in ("name", "brand_kind"):
        if f not in b: bad_req(f"{f} required")
    if b["brand_kind"] not in ("LICENSED", "EVERGREEN"): bad_req("invalid brand_kind")
    if not isinstance(b["name"], str) or not b["name"]: bad_req("name required")
    prop = None; ag = None; tsd = None; tsd_dt = None
    if b["brand_kind"] == "LICENSED":
        pid = b.get("property_id"); aid = b.get("license_agreement_id")
        if pid is None or aid is None:
            bad_req("LICENSED line requires property_id and license_agreement_id")
        prop = db.properties.get(pid)
        if not prop: not_found("property not found")
        ag = db.agreements.get(aid)
        if not ag: not_found("license agreement not found")
        confidential_gate_for_prop(prop)
        st = db.studios.get(prop["studio_id"])
        if st and st["confidentiality_tier"] == "STRICT" and db.clock < prop["_reveal_dt"]:
            raise ApiErr("ERR_CONFIDENTIALITY_BREACH", 422, "STRICT studio: before reveal_date")
        tsd = prop["release_date"]; tsd_dt = prop["_release_dt"]
    else:
        if "target_street_date_input" in b and b["target_street_date_input"] is not None:
            tsd = b["target_street_date_input"]; tsd_dt = parse_iso(tsd)
        else:
            bad_req("EVERGREEN line requires target_street_date_input")
    l = {"id": new_id(), "name": b["name"], "brand_kind": b["brand_kind"],
         "property_id": b.get("property_id") if b["brand_kind"] == "LICENSED" else None,
         "license_agreement_id": b.get("license_agreement_id") if b["brand_kind"] == "LICENSED" else None,
         "target_street_date": tsd,
         "target_street_date_input": b.get("target_street_date_input") if b["brand_kind"] == "EVERGREEN" else None,
         "_tsd_dt": tsd_dt,
         "status": "CONCEPT", "closeout_markdown_pct": None, "closeout_recovery_cents": None}
    stamp_new(l)
    db.lines[l["id"]] = l
    return ok_obj(line_json(l), 201)

@bp.get("/toy-lines/<lid>")
def get_line(lid):
    caller()
    l = db.lines.get(lid)
    if not l: not_found("toy line not found")
    return ok_obj(line_json(l))

@bp.get("/toy-lines")
def list_lines():
    caller()
    items = list(db.lines.values())
    for q, key in (("property_id", "property_id"), ("license_agreement_id", "license_agreement_id"),
                   ("brand_kind", "brand_kind")):
        v = request.args.get(q)
        if v is not None:
            items = [l for l in items if l[key] == v]
    return paged([line_json(l) for l in items])

@bp.post("/toy-lines/<lid>/advance")
def advance_line(lid):
    require_role("BrandManager")
    l = db.lines.get(lid)
    if not l: not_found("toy line not found")
    b = get_body()
    # OCC check comes after state gates per priority 11? No: priority 4 state, 11 OCC.
    # State gates evaluated first per error ordering.
    cur = l["status"]
    if cur == "CONCEPT":
        if l["brand_kind"] == "LICENSED":
            ag = db.agreements.get(l["license_agreement_id"])
            if not ag or ag["status"] != "ACTIVE":
                raise ApiErr("ERR_INVALID_STATE", 409, "license agreement not ACTIVE")
            prop = db.properties.get(l["property_id"])
            if prop and property_lifecycle(prop) == "CONFIDENTIAL":
                raise ApiErr("ERR_INVALID_STATE", 409, "property CONFIDENTIAL")
        nxt = "IN_DEVELOPMENT"
    elif cur == "IN_DEVELOPMENT":
        skus = [s for s in db.skus.values() if s["toy_line_id"] == l["id"]]
        if any(s["safety_status"] != "PASSED" for s in skus):
            raise ApiErr("ERR_SAFETY_GATE", 422, "every SKU must be PASSED")
        if not any(t["toy_line_id"] == l["id"] and t["status"] == "APPROVED" for t in db.tooling_orders.values()):
            raise ApiErr("ERR_INVALID_STATE", 409, "no APPROVED tooling order")
        nxt = "TOOLED"
    elif cur == "TOOLED":
        skids = {s["id"] for s in db.skus.values() if s["toy_line_id"] == l["id"]}
        if not any(c["sku_id"] in skids and c["status"] == "COMMITTED" for c in db.commitments.values()):
            raise ApiErr("ERR_INVALID_STATE", 409, "no COMMITTED commitment")
        nxt = "COMMITTED"
    elif cur == "COMMITTED":
        raise ApiErr("ERR_INVALID_STATE", 409, "COMMITTED advances only via clock")
    else:
        raise ApiErr("ERR_INVALID_STATE", 409, f"cannot advance from {cur}")
    # OCC check (priority 11) before general shape (12): expected version check now
    if "expected_toy_line_version" in b:
        if b["expected_toy_line_version"] != l["version"]:
            raise ApiErr("ERR_STALE_VERSION", 412, "stale version")
    l["status"] = nxt
    touch(l)
    return ok_obj(line_json(l))

@bp.post("/toy-lines/<lid>/revert")
def revert_line(lid):
    require_role("BrandManager")
    l = db.lines.get(lid)
    if not l: not_found("toy line not found")
    cur = l["status"]
    if cur == "IN_DEVELOPMENT":
        if any(t["toy_line_id"] == l["id"] and t["status"] == "APPROVED" for t in db.tooling_orders.values()):
            raise ApiErr("ERR_INVALID_STATE", 409, "APPROVED tooling order exists")
        l["status"] = "CONCEPT"
    elif cur == "TOOLED":
        if any(t["toy_line_id"] == l["id"] and t["status"] == "APPROVED" for t in db.tooling_orders.values()):
            raise ApiErr("ERR_INVALID_STATE", 409, "scrap all tooling orders first")
        l["status"] = "IN_DEVELOPMENT"
    else:
        raise ApiErr("ERR_INVALID_STATE", 409, f"cannot revert from {cur}")
    touch(l)
    return ok_obj(line_json(l))

def markdown_recovery(l, markdown_pct):
    skids = {s["id"] for s in db.skus.values() if s["toy_line_id"] == l["id"]}
    commits = [c for c in db.commitments.values()
               if c["sku_id"] in skids and c["status"] in ("COMMITTED", "AT_RISK")]
    total_units = sum(c["committed_units"] for c in commits)
    if total_units == 0:
        return 0, commits
    weighted = sum(c["committed_units"] * c["unit_price_cents"] for c in commits)
    avg_price = half_up_dec(Decimal(weighted) / Decimal(total_units))
    mp = Decimal(str(markdown_pct))
    if mp < Decimal("0.50"):
        eff = mp
    else:
        eff = Decimal("0.50") + (mp - Decimal("0.50")) / Decimal(2)
    revenue = half_up_dec(Decimal(total_units) * Decimal(avg_price) * eff)
    return revenue, commits

@bp.post("/toy-lines/<lid>/enter_closeout")
def enter_closeout(lid):
    require_role("BrandManager")
    l = db.lines.get(lid)
    if not l: not_found("toy line not found")
    b = get_body()
    cur = l["status"]
    if cur == "COMMITTED":
        if l["brand_kind"] == "LICENSED":
            prop = db.properties.get(l["property_id"])
            if prop and property_lifecycle(prop) != "RELEASED":
                raise ApiErr("ERR_INVALID_STATE", 409, "property not RELEASED")
    elif cur == "ON_SHELF":
        pass
    else:
        raise ApiErr("ERR_INVALID_STATE", 409, f"cannot enter closeout from {cur}")
    mp = b.get("markdown_pct")
    if not isinstance(mp, (int, float)):
        bad_req("markdown_pct required")
    revenue, commits = markdown_recovery(l, mp)
    l["closeout_markdown_pct"] = mp
    l["closeout_recovery_cents"] = revenue
    affected = set()
    for c in commits:
        c["status"] = "CANCELLED"
        touch(c)
        affected.add(c["line_review_id"])
    for rid in affected:
        recompute_shelf(rid)
    l["status"] = "CLOSEOUT"
    touch(l)
    return ok_obj(line_json(l))

@bp.post("/toy-lines/<lid>/exit_closeout")
def exit_closeout(lid):
    require_role("BrandManager")
    l = db.lines.get(lid)
    if not l: not_found("toy line not found")
    if l["status"] != "CLOSEOUT":
        raise ApiErr("ERR_INVALID_STATE", 409, "line not in CLOSEOUT")
    l["status"] = "COMMITTED"
    touch(l)
    return ok_obj(line_json(l))

@bp.post("/toy-lines/<lid>/retire")
def retire_line(lid):
    require_role("BrandManager")
    l = db.lines.get(lid)
    if not l: not_found("toy line not found")
    if l["status"] != "CLOSEOUT":
        raise ApiErr("ERR_INVALID_STATE", 409, "line not in CLOSEOUT")
    skids = {s["id"] for s in db.skus.values() if s["toy_line_id"] == l["id"]}
    for sh in db.shipments.values():
        c = db.commitments.get(sh["commitment_id"])
        if c and c["sku_id"] in skids and sh["status"] == "PLANNED":
            raise ApiErr("ERR_INVALID_STATE", 409, "PLANNED shipment exists")
    if any(t["toy_line_id"] == l["id"] and t["status"] == "APPROVED" for t in db.tooling_orders.values()):
        raise ApiErr("ERR_INVALID_STATE", 409, "APPROVED tooling order exists")
    l["status"] = "RETIRED"
    touch(l)
    return ok_obj(line_json(l))
