from flask import Blueprint, request
from datetime import datetime

import auth
import store
from envelope import success
from errors import err
from helpers import require_field
from routes_deployments import auto_activate_due_orders

bp = Blueprint("clock", __name__)


@bp.post("/membership/_clock/set_current_utc")
def set_clock():
    c = auth.ctx()
    auth.require_roles(c, ["PlatformAdmin"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    v = require_field(body, "to_iso8601")
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", 400, "invalid to_iso8601")
    s = v.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", 400, "invalid to_iso8601")
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    # normalize to UTC Z form
    from datetime import timezone
    dt = dt.astimezone(timezone.utc)
    store.LOGICAL_CLOCK = dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    auto_activate_due_orders()
    return success(200, {"current_utc": store.LOGICAL_CLOCK}, "object")
