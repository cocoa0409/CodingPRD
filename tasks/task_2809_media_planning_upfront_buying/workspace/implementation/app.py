"""Upfront media planning and buying API.

A single Flask process holding all state in memory.  Nothing is persisted and
nothing is seeded: every boot starts from an empty world, which is what makes
per-test-server isolation a genuine wipe.
"""

import os
import threading

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from auth import authenticate
from errors import ApiError
from response import error_response
from routes import ROOT_BLUEPRINTS, UPFRONT_BLUEPRINTS

# One request at a time: the in-memory store has no other synchronisation and
# every business rule reads-then-writes across several collections.
_REQUEST_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in UPFRONT_BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix="/upfront")
    for blueprint in ROOT_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _before():
        _REQUEST_LOCK.acquire()
        g._lock_held = True
        g._touched = set()
        if request.url_rule is None:
            # An unrouteable path is a 404, not an authentication failure.
            return None
        authenticate()
        return None

    @app.teardown_request
    def _teardown(_exc):
        if getattr(g, "_lock_held", False):
            g._lock_held = False
            try:
                _REQUEST_LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_response(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(_exc):
        return (
            jsonify(error_response("ERR_NOT_FOUND", "The requested path does not exist.")),
            404,
        )

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return (
            jsonify(
                error_response(
                    "ERR_METHOD_NOT_ALLOWED",
                    "The requested method is not allowed for this path.",
                )
            ),
            405,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        if isinstance(exc, HTTPException):
            return (
                jsonify(
                    error_response(
                        "ERR_INVALID_REQUEST" if exc.code == 400 else "ERR_NOT_FOUND",
                        exc.description or "The request could not be served.",
                    )
                ),
                exc.code,
            )
        return (
            jsonify(error_response("ERR_INTERNAL", "An unexpected error occurred.")),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
