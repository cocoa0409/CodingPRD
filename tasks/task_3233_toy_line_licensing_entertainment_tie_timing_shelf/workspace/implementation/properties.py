from flask import Blueprint, request
from auth import caller, require_role
from store import db, stamp_new, touch, property_lifecycle
from util import ApiErr, ok_obj, paged, not_found, bad_req, parse_iso, new_id, get_body

bp = Blueprint("properties", __name__)

def prop_json(p):
    return {"id": p["id"], "studio_id": p["studio_id"], "title": p["title"],
            "category": p["category"], "reveal_date": p["reveal_date"],
            "release_date": p["release_date"], "shift_count": p["shift_count"],
            "lifecycle": property_lifecycle(p),
            "created_at": p["created_at"], "updated_at": p["updated_at"],
            "version": p["version"]}

@bp.post("/properties")
def create_property():
    require_role("StudioRep")
    b = get_body()
    for f in ("studio_id", "title", "category", "reveal_date", "release_date"):
        if f not in b: bad_req(f"{f} required")
    st = db.studios.get(b["studio_id"])
    if not st: not_found("studio not found")
    if b["category"] not in ("FILM", "SERIES"): bad_req("invalid category")
    if not isinstance(b["title"], str) or not b["title"]: bad_req("title required")
    rev = parse_iso(b["reveal_date"]); rel = parse_iso(b["release_date"])
    p = {"id": new_id(), "studio_id": st["id"], "title": b["title"],
         "category": b["category"], "reveal_date": b["reveal_date"],
         "release_date": b["release_date"], "shift_count": 0,
         "_reveal_dt": rev, "_release_dt": rel}
    stamp_new(p)
    db.properties[p["id"]] = p
    return ok_obj(prop_json(p), 201)

@bp.get("/properties/<pid>")
def get_property(pid):
    caller()
    p = db.properties.get(pid)
    if not p: not_found("property not found")
    return ok_obj(prop_json(p))

@bp.get("/properties")
def list_properties():
    caller()
    items = list(db.properties.values())
    sid = request.args.get("studio_id")
    if sid is not None:
        items = [p for p in items if p["studio_id"] == sid]
    return paged([prop_json(p) for p in items])

@bp.post("/properties/<pid>/shift_release")
def shift_release(pid):
    require_role("StudioRep")
    p = db.properties.get(pid)
    if not p: not_found("property not found")
    b = get_body()
    if "new_release_date" not in b: bad_req("new_release_date required")
    new_rel = parse_iso(b["new_release_date"])
    p["release_date"] = b["new_release_date"]; p["_release_dt"] = new_rel
    p["shift_count"] += 1
    touch(p)
    # cascade: licensed lines anchored to this property
    for line in db.lines.values():
        if line["brand_kind"] == "LICENSED" and line["property_id"] == p["id"]:
            line["target_street_date"] = p["release_date"]
            line["_tsd_dt"] = new_rel
            touch(line)
            line_skus = [s["id"] for s in db.skus.values() if s["toy_line_id"] == line["id"]]
            # shipments PLANNED
            for sh in db.shipments.values():
                c = db.commitments.get(sh["commitment_id"])
                if c and c["sku_id"] in line_skus and sh["status"] == "PLANNED":
                    sh["street_date"] = p["release_date"]; sh["_sd_dt"] = new_rel
                    touch(sh)
            # commitments COMMITTED -> AT_RISK when review window_start < new release
            for c in db.commitments.values():
                if c["sku_id"] in line_skus and c["status"] == "COMMITTED":
                    r = db.reviews.get(c["line_review_id"])
                    if r and r["_ws_dt"] < new_rel:
                        c["status"] = "AT_RISK"
                        touch(c)
    return ok_obj(prop_json(p))
