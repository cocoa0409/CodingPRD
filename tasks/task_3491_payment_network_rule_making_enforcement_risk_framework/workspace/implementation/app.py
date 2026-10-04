"""Application wiring: the unprefixed logical-clock endpoint, error handlers,
and blueprint registration. All domain resources live under /network; the
clock endpoint is a platform endpoint mounted outside that prefix (PRD 2.4).
"""
import os

from flask import Flask

from auth import require_roles
from clock import CLOCK, parse_iso_datetime, render_ts
from envelope import error_resp, ok
from errors import ApiError, fail
from validation import get_body, require_str

import compliance
import enforcement
import originators
import participants
import returns_rates
import rulemaking
import settlement

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Platform endpoint: logical clock (NOT under /network)
# ---------------------------------------------------------------------------


@app.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    body = get_body()
    to_iso8601 = require_str(body, "to_iso8601")
    parsed = parse_iso_datetime(to_iso8601)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 timestamp")
    CLOCK.set_now(parsed)
    return ok({"current_utc": render_ts(CLOCK.now())})


# ---------------------------------------------------------------------------
# Domain blueprints (all under /network)
# ---------------------------------------------------------------------------

for blueprint in (
    participants.bp,
    originators.bp,
    rulemaking.bp,
    settlement.bp,
    returns_rates.bp,
    enforcement.bp,
    compliance.bp,
):
    app.register_blueprint(blueprint, url_prefix="/network")


# ---------------------------------------------------------------------------
# Error handlers — every error response uses the standard envelope
# ---------------------------------------------------------------------------


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_resp(err.error_id, err.message)


@app.errorhandler(404)
def handle_not_found(err):
    return error_resp("ERR_NOT_FOUND", "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_resp("ERR_NOT_FOUND", "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_resp(err.error_id, err.message)
    code = getattr(err, "code", None)
    if code == 404:
        return error_resp("ERR_NOT_FOUND", "Resource not found")
    if code == 405:
        return error_resp("ERR_NOT_FOUND", "Resource not found")
    return error_resp("ERR_INTERNAL", "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
