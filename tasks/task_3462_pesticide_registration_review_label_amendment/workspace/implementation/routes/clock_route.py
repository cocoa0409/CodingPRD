"""POST /_clock/set_current_utc — the unprefixed platform clock endpoint."""
from flask import Blueprint

import clock
from auth import require_auth, require_role
from envelope import ok
from errors import err
from services.sweep import run as run_sweep
from validate import as_datetime, parse_body, reject_unknown

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    caller = require_auth()
    require_role(caller, ["SystemAdministrator"])
    data = parse_body()
    reject_unknown(data, ["to_iso8601"])
    target = as_datetime(data, "to_iso8601", required=True)

    current = clock.now()
    if target < current:
        err(
            "ERR_INVALID_REQUEST",
            "to_iso8601 must not be strictly before the current logical clock.",
        )
    if target > current:
        clock.advance(target)
        run_sweep(target)
    # Equal is an idempotent no-op.
    return ok({"current_utc": clock.now_iso()}, status=200)
