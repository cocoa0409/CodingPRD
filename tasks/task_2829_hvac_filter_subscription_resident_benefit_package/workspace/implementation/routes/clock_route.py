"""POST /_clock/set_current_utc — operator-only logical-clock repointing."""
from flask import Blueprint

import clock
import envelope
import guards
import validate

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    guards.auth(["ProgramOperator"])
    body = validate.json_body()
    instant = validate.req_instant(body, "to_iso8601")
    clock.set_now(instant)
    return envelope.object_response({"current_utc": clock.now_iso()})
