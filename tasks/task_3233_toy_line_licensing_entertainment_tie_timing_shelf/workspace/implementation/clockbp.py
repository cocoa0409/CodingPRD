from flask import Blueprint
from auth import require_role
from store import db, touch
from util import ok_obj, bad_req, parse_iso, get_body, now_iso

bp = Blueprint("clock", __name__)

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role("PlatformAdmin")
    b = get_body()
    if "to_iso8601" not in b: bad_req("to_iso8601 required")
    dt = parse_iso(b["to_iso8601"])
    db.clock = dt
    db.clock_str = now_iso(dt)
    # COMMITTED lines whose street date reached -> ON_SHELF
    for l in db.lines.values():
        if l["status"] == "COMMITTED" and l["_tsd_dt"] is not None and dt >= l["_tsd_dt"]:
            l["status"] = "ON_SHELF"
            touch(l)
    return ok_obj({"current_utc": db.clock_str})
