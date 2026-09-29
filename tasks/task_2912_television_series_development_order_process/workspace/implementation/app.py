"""Television Series Development & Order Process API.

A single-process Flask application whose entire state lives in Python dicts
(see store.py).  Nothing is persisted and nothing is seeded: every boot starts
with an empty store and the logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from responses import error_response
import routes_deal
import routes_pilot
import routes_pitch
import routes_project
import routes_registry
import routes_series


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_pitch.bp)
    app.register_blueprint(routes_project.bp)
    app.register_blueprint(routes_deal.bp)
    app.register_blueprint(routes_pilot.bp)
    app.register_blueprint(routes_series.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed for this path.", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "The request could not be parsed.", 400)
        return error_response("ERR_INTERNAL", exc.description or "Unexpected error.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover -- defensive
        return error_response("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
