from flask import Blueprint

import db
import services
from errors import fail
from middleware import auth_context, require_role, body, locked
from response import success
from util import fmt_ts, parse_iso_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@locked
def set_clock():
    auth_context_uid, role = auth_context()
    data = body()
    raw = data.get("to_iso8601")
    if raw is None:
        fail("ERR_VALIDATION", "to_iso8601 is required")
    target = parse_iso_datetime(raw)
    if target is None:
        fail("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 timestamp")
    require_role(role, ["ProgramOffice"])
    db.store.clock = target
    lapsed, separated, activated = services.run_sweeps()
    return success(
        {
            "current_utc": fmt_ts(db.now()),
            "employers_lapsed": lapsed,
            "members_separated": separated,
            "matches_activated": activated,
        }
    )
