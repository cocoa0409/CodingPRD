"""Fiber Route Engineering & Permitting API.

Flask application factory.  All state lives in process memory (see store.py):
every boot starts from an empty store and a logical clock reading
2026-08-01T00:00:00Z, and nothing is ever seeded, persisted or read from disk.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import api_design
import api_field
import api_permit
import api_route
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(api_route.bp)
    app.register_blueprint(api_field.bp)
    app.register_blueprint(api_permit.bp)
    app.register_blueprint(api_design.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if status == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not allowed for this path.",
                405,
            )
        if status == 400:
            return error_response("ERR_INVALID_REQUEST", "The request payload is malformed.", 400)
        return error_response("ERR_INTERNAL", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", "An unexpected internal error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
