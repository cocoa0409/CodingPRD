"""The deterministic logical clock route (PRD §3.8)."""

from flask import Blueprint

import clock
import middleware
import response
import validate
from errors import ERR_INVALID_REQUEST, fail
from services import environments

bp = Blueprint("test_driving", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.require("PlatformAdmin")
    b = validate.body()
    raw = b.value("current_utc")
    if not isinstance(raw, str) or raw.strip() == "":
        fail(ERR_INVALID_REQUEST, "Field 'current_utc' is required.")

    parsed = clock.try_parse(raw)
    if parsed is None:
        fail(ERR_INVALID_REQUEST, "Field 'current_utc' must be an ISO 8601 UTC instant.")

    clock.set_now(parsed)
    environments.recompute_all_clock_projections()
    return response.ok({"current_utc": clock.iso(clock.now())})