"""Wholesale Broker Channel API - application entry point.

Storage is purely in memory. The store starts empty on every process boot:
no entity is seeded, preloaded, registered or hardcoded here.
"""

import os
import traceback

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from middleware import ROLE_TABLE

import routes.brokers
import routes.licenses
import routes.financials
import routes.exclusivity
import routes.pricing_routes
import routes.loans_routes
import routes.quality_routes
import routes.clock_routes

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

API_PREFIX = "/wholesale-channel"

# Register every resource group's blueprints.
for module in (
    routes.brokers,
    routes.licenses,
    routes.financials,
    routes.exclusivity,
    routes.pricing_routes,
    routes.loans_routes,
    routes.quality_routes,
    routes.clock_routes,
):
    for blueprint in module.BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    body = error_body(exc.error_id, exc.message)
    return jsonify(body), exc.http_status


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    body = error_body("ERR_INVALID_REQUEST", exc.description or "Malformed request.")
    return jsonify(body), exc.code


@app.errorhandler(Exception)
def handle_unexpected(exc):
    traceback.print_exc()
    body = error_body("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc)
    return jsonify(body), 400


@app.route(API_PREFIX, methods=["GET"])
def api_root():
    return jsonify({
        "meta": {"api_request_id": "req_ROOT", "api_request_timestamp": None},
        "response_type": "object",
        "data": {"service": "wholesale-broker-channel"},
    })


@app.errorhandler(404)
def handle_not_found(exc):
    body = error_body("ERR_BROKER_NOT_FOUND", "No such route.")
    return jsonify(body), 404


# Every declared route is registered below; the table documents the expected
# (method, rule) pairs so the surface can be audited without guessing.
REGISTERED_CONTRACT = sorted(
    (method, path) for (method, path) in ROLE_TABLE.keys()
)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)