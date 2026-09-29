"""Retail Health Clinic Operations & Scope Protocols API.

A Flask application holding all state in process memory.  Every launch starts
from a completely empty store and a logical clock reading 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

import r_clinical
import r_oversight
import r_queue
import r_reference
import r_staffing
import r_visits


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(r_reference.bp)
    app.register_blueprint(r_staffing.bp)
    app.register_blueprint(r_queue.bp)
    app.register_blueprint(r_visits.bp)
    app.register_blueprint(r_clinical.bp)
    app.register_blueprint(r_oversight.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "The method is not allowed for this resource.",
                405,
            )
        if exc.code == 400:
            return error_response(
                "ERR_VALIDATION", "The request could not be parsed.", 400
            )
        return error_response(
            "ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
