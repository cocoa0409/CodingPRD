from flask import Blueprint

import common
from common import (
    API_PREFIX, db, authenticate, json_body, fail, req_string, parse_dt,
    clock_iso, ROLE_ADMIN,
)
from cascades import epoch_sweep

bp = Blueprint("clock", __name__)


@bp.route(API_PREFIX + "/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate([ROLE_ADMIN])
    body = json_body()
    raw = req_string(body, "to_iso8601")
    parsed = parse_dt(raw)
    if parsed is None:
        fail("ERR_VALIDATION", "Field 'to_iso8601' must be an ISO 8601 UTC datetime.")

    db.clock = parsed
    counters = epoch_sweep()

    data = {"current_utc": clock_iso()}
    data.update(counters)
    return {"meta": common.base_meta(), "response_type": "object", "data": data}, 200
