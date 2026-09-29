"""The logical UTC clock control endpoint (PRD s2.7)."""

from flask import Blueprint

import shape
from authz import admit
from envelope import object_response
from store import clock, iso

bp = Blueprint("clock", __name__)


@bp.route("/valet/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    admit(("PlatformAdmin",))
    body = shape.body()
    target = shape.req_instant(body, "to_iso8601")
    clock.set(target)
    # repositioning the clock is not a domain mutation: nothing is written
    return object_response({"current_utc": iso(clock.now())})
