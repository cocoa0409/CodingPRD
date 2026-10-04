"""ATFM API server entry point.

Flask app wiring: registers every route blueprint, installs the envelope
error handlers, and runs the development server on 0.0.0.0:$PORT (default
10000) in the foreground. The store starts empty on every boot; no seeding.
"""

import os

from flask import Flask, g

from errors import ApiError
from util import error_response

from routes_clock import bp as clock_bp
from routes_events import bp as events_bp
from routes_facilities import bp as facilities_bp
from routes_flights import bp as flights_bp
from routes_forecasts import bp as forecasts_bp
from routes_ga import bp as ga_bp
from routes_ledgers import bp as ledgers_bp
from routes_ops import bp as ops_bp
from routes_reroutes import bp as reroutes_bp
from routes_slots import bp as slots_bp
from routes_tmis import bp as tmis_bp


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    @app.before_request
    def _init_request_state():
        # Per-request mutation registry (PRD 2.10: each entity mutated by a
        # request, including cascade targets, bumps version exactly once).
        g._touched_registry = set()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_not_found(exc):
        return error_response("ERR_INVALID_REQUEST", "route not found", 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(exc):
        return error_response(
            "ERR_INVALID_REQUEST", "method not allowed on this route", 405
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "internal error: %s" % exc, 500)

    for blueprint in (
        clock_bp,
        facilities_bp,
        events_bp,
        forecasts_bp,
        tmis_bp,
        flights_bp,
        slots_bp,
        ops_bp,
        ga_bp,
        reroutes_bp,
        ledgers_bp,
    ):
        app.register_blueprint(blueprint)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
