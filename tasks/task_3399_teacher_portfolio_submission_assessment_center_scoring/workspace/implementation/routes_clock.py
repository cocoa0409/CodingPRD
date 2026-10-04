"""POST /_clock/set_current_utc — logical clock advance + sweeps (PRD 2.4)."""
from flask import Blueprint

import constants as C
import domain
from response import ok
from store import DB, fmt_dt
from validation import auth_headers, require_role, body, req_field, parse_dt_field

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = auth_headers()
    require_role(role, [C.ROLE_BOARD_ADMIN])
    data = body()
    new_clock = parse_dt_field(req_field(data, "to_iso8601"), "to_iso8601")
    domain.sweep_clock(new_clock)
    return ok({"current_utc": fmt_dt(DB.clock)})
