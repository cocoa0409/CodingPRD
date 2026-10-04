"""The logical clock — UNPREFIXED (lives outside /enforcement)."""
from flask import Blueprint

import envelope
import requtil
import store
from timeutil import parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _user_id, role = requtil.context()
    requtil.require_role(role, ["PlatformAdmin"])
    body = requtil.json_body()
    raw = requtil.need_datetime(body, "to_iso8601")
    with store.db.lock:
        store.db.clock_dt = parse_iso(raw)
        store.db.clock_raw = raw
        store.sweep()
    return envelope.success({"current_utc": store.db.clock_raw}, 200)
