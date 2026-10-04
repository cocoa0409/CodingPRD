"""The logical-clock endpoint — deliberately mounted OUTSIDE the /msrb prefix."""
from flask import Blueprint

import clock_ops
import serializers
import store
from respond import ok
from validators import get_body, req_datetime, require_auth, require_role

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = require_auth()
    require_role(role, ("SystemAdmin",))
    body = get_body()
    to_dt = req_datetime(body, "to_iso8601")
    effects = clock_ops.set_clock(to_dt)
    return ok(
        {
            "current_utc": serializers.fmt_clock(store.now()),
            "epoch_effects": effects,
        },
        200,
    )
