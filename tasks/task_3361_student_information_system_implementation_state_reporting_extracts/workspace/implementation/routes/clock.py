"""POST /_clock/set_current_utc — the PlatformAdmin-only logical clock."""
from flask import Blueprint

from dates import fmt_dt
from db import set_clock
from middleware import auth_context, require_role
from response import ok_obj
from validators import body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _uid, role = auth_context()
    data = body()
    current = req_dt(data, "current_utc")
    require_role(role, {"PlatformAdmin"})
    set_clock(current)
    return ok_obj({"current_utc": fmt_dt(current)}, 200)
