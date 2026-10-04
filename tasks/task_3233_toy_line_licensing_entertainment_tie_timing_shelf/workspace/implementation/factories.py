from flask import Blueprint
from auth import caller, require_role
from store import db, stamp_new
from util import ok_obj, not_found, bad_req, new_id, get_body

bp = Blueprint("factories", __name__)

def fac_json(f):
    return {"id": f["id"], "name": f["name"],
            "capacity_units_per_month": f["capacity_units_per_month"],
            "tooling_lead_weeks": f["tooling_lead_weeks"],
            "created_at": f["created_at"], "updated_at": f["updated_at"],
            "version": f["version"]}

@bp.post("/factories")
def create_factory():
    require_role("PlatformAdmin")
    b = get_body()
    for f in ("name", "capacity_units_per_month", "tooling_lead_weeks"):
        if f not in b: bad_req(f"{f} required")
    if not isinstance(b["name"], str) or not b["name"]: bad_req("name required")
    if not isinstance(b["capacity_units_per_month"], int) or b["capacity_units_per_month"] < 1:
        bad_req("capacity_units_per_month must be >= 1")
    if not isinstance(b["tooling_lead_weeks"], int) or b["tooling_lead_weeks"] < 0:
        bad_req("tooling_lead_weeks must be non-negative int")
    f = {"id": new_id(), "name": b["name"],
         "capacity_units_per_month": b["capacity_units_per_month"],
         "tooling_lead_weeks": b["tooling_lead_weeks"]}
    stamp_new(f)
    db.factories[f["id"]] = f
    return ok_obj(fac_json(f), 201)

@bp.get("/factories/<fid>")
def get_factory(fid):
    caller()
    f = db.factories.get(fid)
    if not f: not_found("factory not found")
    return ok_obj(fac_json(f))
