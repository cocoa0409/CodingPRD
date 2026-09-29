"""Apartment Doorstep Trash Valet Service API.

Flask application factory and error handling.  Storage is in-memory only and
starts completely empty on every process start: every entity is created through
the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import DEFAULT_MESSAGE, ERROR_HTTP, ApiError

import r_clock
import r_contractor
import r_incident
import r_night
import r_property
import r_resident
import r_route
import r_scan
import r_statement


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(r_property.bp)
    app.register_blueprint(r_resident.bp)
    app.register_blueprint(r_contractor.bp)
    app.register_blueprint(r_night.bp)
    app.register_blueprint(r_route.bp)
    app.register_blueprint(r_scan.bp)
    app.register_blueprint(r_incident.bp)
    app.register_blueprint(r_statement.bp)
    app.register_blueprint(r_clock.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _handle_405(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)

    @app.errorhandler(HTTPException)
    def _handle_http(exc):
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST",
                DEFAULT_MESSAGE.get("ERR_INVALID_REQUEST", "Malformed request."),
                ERROR_HTTP.get("ERR_INVALID_REQUEST", 422),
            )
        return error_response("ERR_HTTP_ERROR", exc.description or "HTTP error.", exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
