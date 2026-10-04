"""Multi-Brand Portfolio Rationalization API — entry point.

Flask app: registers all route blueprints under /portfolio plus the
UNPREFIXED platform clock endpoint POST /_clock/set_current_utc.
"""

import os
import sys

from flask import Flask

import clock
import errors
from envelope import success, error_response
from rbac import authenticate, synchronized
from validation import body_json, f_dt

import routes_foundation
import routes_items
import routes_cases
import routes_divestitures
import routes_tsas
import routes_transfers
import routes_negotiations
import routes_capital

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_foundation.bp)
app.register_blueprint(routes_items.bp)
app.register_blueprint(routes_cases.bp)
app.register_blueprint(routes_divestitures.bp)
app.register_blueprint(routes_tsas.bp)
app.register_blueprint(routes_transfers.bp)
app.register_blueprint(routes_negotiations.bp)
app.register_blueprint(routes_capital.bp)


# --- platform endpoint (UNPREFIXED, outside /portfolio) ---
@app.post("/_clock/set_current_utc")
@synchronized
def set_current_utc():
    # All six roles may advance the clock; authentication (steps 1-2)
    # still applies, and every declared role is permitted.
    authenticate()
    body = body_json(required=True)
    to = f_dt(body, "to_iso8601")
    clock.set_current(to)
    return success({"current_utc": clock.iso(to)})


# --- error handlers ---
@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response(errors.ApiError(
        "ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(errors.ApiError(
        "ERR_INVALID_REQUEST", 400, "method not allowed on this path"))


@app.errorhandler(500)
def handle_internal(_err):
    return error_response(errors.ApiError(
        "ERR_INVALID_REQUEST", 500, "internal server error"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"portfolio-rationalization api booting on 0.0.0.0:{port} "
          f"logical_clock={clock.iso(clock.now())}", file=sys.stderr, flush=True)
    app.run(host="0.0.0.0", port=port, threaded=True)
