"""Frozen Potato Processing & Foodservice Specification Supply API.

Entry point: builds the Flask app, registers all route blueprints, and maps
ApiError to the PRD section 2.2 error envelope. Storage is in-memory only;
the store starts empty on every boot (per-test-server isolation restarts this
process for every test).
"""

import os

from flask import Flask, jsonify

import routes_agreements
import routes_chains
import routes_clock
import routes_contracts
import routes_facilities
import routes_growers
import routes_lots
import routes_runs
import routes_shipments
import routes_shortage
import routes_specs
from errors import ApiError
from response import error_body

_BLUEPRINTS = (
    routes_clock.bp,
    routes_growers.bp,
    routes_contracts.bp,
    routes_lots.bp,
    routes_facilities.bp,
    routes_specs.bp,
    routes_chains.bp,
    routes_agreements.bp,
    routes_runs.bp,
    routes_shipments.bp,
    routes_shortage.bp,
)


def create_app():
    app = Flask(__name__)
    for bp in _BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        resp = jsonify(error_body(e.error_id, e.message))
        resp.status_code = e.http_status
        return resp

    @app.errorhandler(404)
    def handle_not_found(e):
        resp = jsonify(error_body("ERR_NOT_FOUND", "Route not found"))
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        resp = jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed"))
        resp.status_code = 405
        return resp

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        resp = jsonify(error_body("ERR_INTERNAL_ERROR", "Internal server error"))
        resp.status_code = 500
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
