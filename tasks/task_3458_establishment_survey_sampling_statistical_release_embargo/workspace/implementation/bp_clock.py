"""POST /_clock/set_current_utc — the logical clock (PRD 2.4). Mounted OUTSIDE
the /survey prefix. ProgramAdmin only. The clock may be rewound."""
from flask import Blueprint

from authz import get_auth, require_role
from envelope import ok
from store import set_clock, now, fmt_ts
from validate import get_body, req_instant

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _user, role = get_auth()
    require_role(role, {"ProgramAdmin"})
    data = get_body()
    instant = req_instant(data, "to_iso8601")
    set_clock(instant)
    return ok({"current_utc": fmt_ts(now())})
