"""Drone Pilot Certification & Airspace Authorization API.

Boots a fresh, entirely in-memory service on every invocation: no seeded data,
no persistence, no disk cache.  Every entity is created through the API.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_accident
import routes_aircraft
import routes_airspace
import routes_flight
import routes_insurance
import routes_pilot
import routes_waiver
from errors import ApiError

PREFIX = "/drone-ops"


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False
    for module in (routes_pilot, routes_aircraft, routes_airspace, routes_waiver,
                   routes_insurance, routes_flight, routes_accident):
        app.register_blueprint(module.bp, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return envelope.error("ERR_NOT_FOUND", "no such route", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return envelope.error("ERR_INVALID_REQUEST",
                              "method not allowed on this route", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return envelope.error(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            if exc.code in (301, 302, 307, 308):
                return exc
            return envelope.error("ERR_INVALID_REQUEST", exc.description or "",
                                  exc.code or 400)
        app.logger.exception("unhandled error")
        return envelope.error("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False, debug=False)
