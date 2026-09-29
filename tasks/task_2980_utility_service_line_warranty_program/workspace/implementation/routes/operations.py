"""The two operational capabilities: the overnight run and the logical clock."""

from flask import Blueprint

import config
import timeutil
from response import object_response
from services import nightly
from store import store
from validation import Field, current_user_id, parse_body, require_role

bp = Blueprint("operations", __name__)

NIGHTLY_SPEC = {}
CLOCK_SPEC = {"to_iso8601": Field("instant", required=True)}


@bp.post("/operations/nightly-run")
def nightly_run():
    current_user_id()
    require_role(config.ROLE_OPERATIONS_ADMIN, config.ROLE_PLATFORM_ADMIN)
    parse_body(NIGHTLY_SPEC)
    return object_response(nightly.run())


@bp.post("/_clock/set_current_utc")
def set_clock():
    current_user_id()
    require_role(config.ROLE_PLATFORM_ADMIN, config.ROLE_OPERATIONS_ADMIN)
    body = parse_body(CLOCK_SPEC)
    # Setting the clock mutates no domain entity; it only changes what the
    # temporal rules see from here on.
    store.set_clock(body["to_iso8601"])
    return object_response({"current_utc": timeutil.render_instant(store.now())})
