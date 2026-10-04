"""On-Site Fuel Cell Power Purchase & Availability Guarantee API.

Flask entry point: registers the route groups, installs the response envelope
error handlers and runs the server in the foreground on $PORT.
"""

import os
import sys
import traceback

from flask import Flask

import middleware
import store
import transitions
from errors import ERR_INVALID_REQUEST, ApiError
from routes_customers import bp as customers_bp
from routes_deliveries import bp as deliveries_bp
from routes_ops import bp as ops_bp
from routes_ppas import bp as ppas_bp
from routes_service import bp as service_bp
from routes_settlement import bp as settlement_bp
from routes_sites import bp as sites_bp

app = Flask(__name__)
app.config["PROPAGATE_EXCEPTIONS"] = False
try:
    app.json.sort_keys = False
except AttributeError:  # Flask < 2.2
    app.config["JSON_SORT_KEYS"] = False

for blueprint in (sites_bp, customers_bp, ppas_bp, service_bp, deliveries_bp,
                  settlement_bp, ops_bp):
    app.register_blueprint(blueprint)


@app.before_request
def _tick():
    """Deferred, clock-driven actions fire before the request is served."""
    transitions.process_deferred()


@app.route("/health", methods=["GET"])
def health():
    return middleware.ok({"status": "ok", "current_utc": store.now_iso()})


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return middleware.error_response(exc)


@app.errorhandler(404)
def _handle_not_found(_exc):
    return middleware.error_response(
        ApiError("ERR_REFERENCE_NOT_FOUND", "no such resource", 404))


@app.errorhandler(405)
def _handle_method(_exc):
    return middleware.error_response(
        ApiError(ERR_INVALID_REQUEST, "method is not admitted on this path", 405))


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    traceback.print_exc(file=sys.stderr)
    return middleware.error_response(
        ApiError(ERR_INVALID_REQUEST, "the request could not be processed", 500))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
