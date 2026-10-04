"""Logical clock and ops-run sweep endpoints."""
from flask import Blueprint

import db
import services
from errors import err_invalid_request
from response import body, get_auth, require_roles, success_obj, req_ts

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    data = body()
    to = req_ts(data, "to_iso8601")
    db.set_clock(to)
    return success_obj({"current_utc": db.fmt_ts(db.now())})


@bp.post("/ops/run")
def ops_run():
    _, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    equipment_marked = services.sweep_equipment(list(db.equipment.values()))
    licenses_expired = services.sweep_licenses(list(db.licenses.values()))
    rematch_cleared = services.clear_stale_rematch_flags()
    return success_obj({
        "equipment_marked_overdue": equipment_marked,
        "licenses_expired": licenses_expired,
        "rematch_flags_cleared": rematch_cleared,
    })
