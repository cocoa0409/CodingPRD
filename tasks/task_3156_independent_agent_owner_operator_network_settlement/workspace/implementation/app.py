"""Independent Agent & Owner-Operator Network Settlement API.

Boots with an empty in-memory store — nothing is seeded, preloaded or read from
disk. Every row a test needs is built at runtime through the declared endpoints.
"""
from __future__ import annotations

import os

from flask import Flask

from common import ApiError, bind_context, error_response
from routes import BLUEPRINTS


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _bind():
        bind_context()

    @app.errorhandler(404)
    def _handle_not_found(exc):
        return error_response(ApiError(
            "ERR_INVALID_REQUEST", 404,
            "No route matches the requested path and method."))

    @app.errorhandler(405)
    def _handle_method(exc):
        return error_response(ApiError(
            "ERR_INVALID_REQUEST", 405,
            "The requested method is not allowed on this path."))

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        # Flask wraps a view's HTTPException in a containing handler, so the
        # catalog error is recovered from the exception chain before falling
        # back to a generic refusal.
        cursor = exc
        while cursor is not None:
            if isinstance(cursor, ApiError):
                return error_response(cursor)
            cursor = getattr(cursor, "original_exception", None) or \
                getattr(cursor, "__cause__", None)
        app.logger.exception("unhandled error")
        return error_response(ApiError(
            "ERR_INVALID_REQUEST", 400, "The request could not be completed."))

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)