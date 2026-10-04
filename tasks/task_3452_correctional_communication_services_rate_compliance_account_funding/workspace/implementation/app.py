"""Entry point: Flask app, blueprint registration, the platform-level logical
clock endpoint (mounted OUTSIDE the /comm-services prefix), and error
handlers that keep every response in the PRD section 2.2 envelope.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_accounts
import routes_calls
import routes_caps
import routes_complaints
import routes_contracts
import routes_facilities
import routes_inmates
import routes_messages
import routes_recipients
import routes_refunds
import routes_schedules
import routes_video
from core import (CLOCK, ApiError, auth, body, err_response, fmt_dt, ok_obj,
                  parse_dt, req_field)

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (routes_facilities, routes_caps, routes_contracts,
               routes_schedules, routes_inmates, routes_accounts,
               routes_recipients, routes_calls, routes_video,
               routes_messages, routes_refunds, routes_complaints):
    app.register_blueprint(module.bp)


@app.post("/_clock/set_current_utc")
def set_current_utc():
    """PlatformAdmin-only test-driving capability; platform-level mount."""
    auth(["PlatformAdmin"])
    data = body()
    value = req_field(data, "current_utc")
    dt = parse_dt(value, "current_utc")
    CLOCK.set(dt)
    return ok_obj({"current_utc": fmt_dt(dt)})


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return err_response(exc)


@app.errorhandler(404)
def handle_not_found(exc):
    return err_response(ApiError("ERR_NOT_FOUND", 404,
                                 "The requested path does not exist"))


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return err_response(ApiError("ERR_NOT_FOUND", 405,
                                 "The requested method is not allowed here"))


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, HTTPException):
        code = exc.code or 500
        return err_response(ApiError("ERR_INTERNAL", code, exc.name))
    return err_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
