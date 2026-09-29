"""The logical program clock (PRD 2.4)."""

from flask import Blueprint

import response
import util
import validation
from middleware import endpoint

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint("ProgramAdmin")
def set_current_utc():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    target = validation.req_instant(body, "to_iso8601")
    util.clock.set(target)
    return response.ok({"current_utc": util.fmt_instant(util.clock.now())})
