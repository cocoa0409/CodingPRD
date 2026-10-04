"""Identity Protection & Return Fraud API — Flask entry point.

Mounts all 55 domain endpoints under /identity-protection plus the single
platform-level logical-clock endpoint at /_clock/set_current_utc (unprefixed).
State is in-memory only; every fresh process boots with an empty store.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

import routes_advocate
import routes_cases
import routes_clock
import routes_configs
import routes_conflicts
import routes_holds
import routes_offices
import routes_pins
import routes_reports
import routes_returns
import routes_schemes
import routes_taxpayers

app = Flask(__name__)
app.json.sort_keys = False

for module in (
    routes_taxpayers,
    routes_reports,
    routes_pins,
    routes_returns,
    routes_holds,
    routes_cases,
    routes_offices,
    routes_conflicts,
    routes_schemes,
    routes_advocate,
    routes_configs,
    routes_clock,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(e):
    status = e.code or 500
    if status == 404:
        error_id = "ERR_NOT_FOUND"
    elif status == 405:
        error_id = "ERR_METHOD_NOT_ALLOWED"
    else:
        error_id = "ERR_INVALID_REQUEST"
    return error_response(error_id, e.description or "HTTP error", status)


@app.errorhandler(Exception)
def handle_unexpected(e):
    return error_response("ERR_INTERNAL", "Internal server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
