# POST /_clock/set_current_utc — advance the logical clock; runs the
# agreement-expiry sweep (PRD 2.4): ACTIVE agreements whose end date falls at
# or before the new clock become EXPIRED. Quarantine lots are NOT rejected.
from flask import Blueprint

import clock
from errors import err
from middleware import authenticate, authorize
from response import success
from store import db, flush_dirty, mark
from validation import Shape, body_json, get_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _user_id, role = authenticate()
    authorize(role, ["PlatformAdmin"])

    body = body_json()
    shape = Shape()
    _raw, new_now = get_dt(body, "to_iso8601", shape)
    shape.raise_if_any()

    clock.set_now(new_now)

    # Agreement-expiry sweep.
    for supplier in db["suppliers"].values():
        if supplier["agreement_status"] != "ACTIVE":
            continue
        end_dt = supplier["_dt"].get("agreement_end_date")
        if end_dt is not None and end_dt <= new_now:
            supplier["agreement_status"] = "EXPIRED"
            mark(supplier)
    flush_dirty()

    return success({}, response_type="object", status=200)
