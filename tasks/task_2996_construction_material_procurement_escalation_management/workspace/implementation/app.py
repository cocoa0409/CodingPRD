"""Construction Material Procurement & Escalation Management API.

A single-process, in-memory Flask application. All state lives in
`store.store` and is discarded when the process exits, so every fresh boot
starts from an empty world with the logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import (
    agreements,
    change_orders,
    clock,
    commitments,
    projects,
    quotes,
    storage,
    substitutions,
    suppliers,
)

BLUEPRINTS = (
    projects.bp,
    suppliers.bp,
    quotes.bp,
    agreements.bp,
    commitments.bp,
    storage.bp,
    substitutions.bp,
    change_orders.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_not_found(exc):
        return error_response(
            "ERR_RECORD_NOT_FOUND", "the requested resource does not exist", 404
        )

    @app.errorhandler(405)
    def _handle_method_not_allowed(exc):
        return error_response(
            "ERR_INVALID_REQUEST", "the method is not allowed for this resource", 405
        )

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return _handle_not_found(exc)
        if status == 405:
            return _handle_method_not_allowed(exc)
        return error_response("ERR_INVALID_REQUEST", exc.description or "bad request", 422)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "unexpected server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
