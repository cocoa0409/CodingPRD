"""Reinsurance Treaty Placement API.

A single Flask process holding every entity in memory.  Nothing is seeded: the
14 collections in db.py start empty on every boot and all state is created by
callers through the declared endpoints.  The logical clock starts at the
mandatory default 2026-08-01T00:00:00.000Z and never reads the wall clock.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import routes
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return response.error_response(err)

    @app.errorhandler(404)
    def _not_found(err):
        return response.error(
            "ERR_NOT_FOUND", "the requested resource does not exist", 404)

    @app.errorhandler(405)
    def _not_allowed(err):
        return response.error(
            "ERR_METHOD_NOT_ALLOWED",
            "the method is not allowed for the requested path", 405)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 400:
            return response.error("ERR_VALIDATION", "malformed request", 400)
        return response.error(
            "ERR_REQUEST_FAILED", err.description or "request failed",
            err.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return response.error_response(err)
        return response.error("ERR_INTERNAL", str(err) or "internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
