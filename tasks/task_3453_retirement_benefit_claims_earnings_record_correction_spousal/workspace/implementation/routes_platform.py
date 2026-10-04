"""Platform endpoints — intentionally UNPREFIXED (SCAFFOLD.yaml §1.5):
POST /_clock/set_current_utc and POST /_batch/run-monthly-cycle, both
restricted to ProgramAdministrator.
"""

from flask import Blueprint

import timeutil as tu
import validation as v
from batch import run_monthly_cycle
from db import store, fmt_ts
from envelope import ok
from errors import ApiError, ERR_INVALID_REQUEST
from security import ROLE_PROGRAM_ADMINISTRATOR, authenticate, require_role

bp = Blueprint("platform", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    ctx = authenticate()
    require_role(ctx, {ROLE_PROGRAM_ADMINISTRATOR})
    body = v.get_body()
    raw = v.req_str(body, "to_iso8601")
    dt = tu.parse_iso8601(raw)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO-8601 UTC instant.")
    store.clock = dt
    return ok({"current_utc": fmt_ts(store.clock)})


@bp.route("/_batch/run-monthly-cycle", methods=["POST"])
def run_monthly_cycle_endpoint():
    ctx = authenticate()
    require_role(ctx, {ROLE_PROGRAM_ADMINISTRATOR})
    body = v.get_body()
    raw = body.get("run_month")
    if raw is None:
        run_month = store.clock_month()
    else:
        run_month = tu.parse_month_str(raw)
        if run_month is None:
            raise ApiError(ERR_INVALID_REQUEST, "run_month must be a YYYY-MM month identifier.")
    return ok(run_monthly_cycle(run_month))
