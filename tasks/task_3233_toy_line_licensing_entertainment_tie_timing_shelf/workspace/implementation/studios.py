from flask import Blueprint
from auth import caller, require_role
from store import db, stamp_new, touch, property_lifecycle
from util import ApiErr, ok_obj, paged, not_found, bad_req, parse_iso, new_id, now_iso

bp = Blueprint("studios", __name__)

def studio_json(s):
    return {k: s[k] for k in ("id", "name", "confidentiality_tier", "status",
                              "created_at", "updated_at", "version")}

@bp.post("/studios")
def create_studio():
    require_role("PlatformAdmin")
    b = _body()
    name = b.get("name")
    if not isinstance(name, str) or not name:
        bad_req("name required")
    tier = b.get("confidentiality_tier", "STANDARD")
    if tier not in ("STANDARD", "STRICT"):
        bad_req("invalid confidentiality_tier")
    s = {"id": new_id(), "name": name, "confidentiality_tier": tier, "status": "ACTIVE"}
    stamp_new(s)
    db.studios[s["id"]] = s
    return ok_obj(studio_json(s), 201)

@bp.get("/studios/<sid>")
def get_studio(sid):
    caller()
    s = db.studios.get(sid)
    if not s: not_found("studio not found")
    return ok_obj(studio_json(s))

def _body():
    from util import get_body
    return get_body()
