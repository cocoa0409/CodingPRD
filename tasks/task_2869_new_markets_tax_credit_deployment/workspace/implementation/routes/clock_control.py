"""The logical-clock control endpoint (outside the /nmtc prefix)."""
from flask import Blueprint

import clock
import validators as v
from middleware import endpoint

bp = Blueprint("clock_control", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["CertifyingAgency"])
def set_current_utc():
    data = v.body()
    target = v.req_instant(data, "to_iso8601")
    return {"current_utc": clock.set_now(target)}
