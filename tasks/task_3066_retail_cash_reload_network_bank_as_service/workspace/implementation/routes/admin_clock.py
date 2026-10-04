"""The administrative logical-clock capability, mounted at the API root."""

from flask import Blueprint

import errors
import middleware
import requests_helpers as rh
import response
import timeutil

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.authenticate(("PlatformAdmin",))
    data = rh.body()
    value = rh.require(data, "current_utc")
    try:
        parsed = timeutil.parse(value)
    except (ValueError, TypeError):
        raise errors.invalid_request("current_utc must be an ISO 8601 instant.")
    if parsed is None:
        raise errors.invalid_request("current_utc must be an ISO 8601 instant.")
    timeutil.set_now(parsed)
    return response.ok({})