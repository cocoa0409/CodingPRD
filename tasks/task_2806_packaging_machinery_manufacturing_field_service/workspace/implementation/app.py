"""Packaging machinery OEM field-service API (PRD.md).

Storage is in-memory only: every process start begins with completely empty
tables and no seeded rows of any kind.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_assets
import routes_claims
import routes_foundation
import routes_orders
import routes_service
import routes_slots
import routes_tests
import routes_trials
from errors import ApiError

PREFIX = "/packaging-oem"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for module in (routes_foundation, routes_trials, routes_orders,
                   routes_slots, routes_tests, routes_assets,
                   routes_service, routes_claims):
        app.register_blueprint(module.bp, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return envelope.error("ERR_METHOD_NOT_ALLOWED",
                              "Method not allowed on this path.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return envelope.error("ERR_INVALID_REQUEST",
                                  exc.description or "Malformed request.", 400)
        return envelope.error("ERR_HTTP_%d" % (exc.code or 500),
                              exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return envelope.error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
