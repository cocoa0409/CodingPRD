"""Political Advertising Compliance & Lowest Unit Rate API."""
import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import core
from core import ApiError, error_response
import routes_admin
import routes_compliance
import routes_orders


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_admin.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_compliance.bp)

    # Every request mutates or reads one shared in-memory store; serialising
    # requests keeps cascades and the optimistic-concurrency checks atomic.
    request_lock = threading.Lock()

    @app.before_request
    def _acquire_lock():
        request_lock.acquire()
        g._request_lock_held = True

    @app.teardown_request
    def _release_lock(exc=None):
        if getattr(g, "_request_lock_held", False):
            g._request_lock_held = False
            request_lock.release()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND", "resource not found", 404))
        if err.code == 405:
            return error_response(ApiError("ERR_INVALID_REQUEST", "method not allowed", 405))
        if err.code in (400, 415):
            return error_response(
                ApiError("ERR_INVALID_REQUEST", "malformed request body", 422))
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err), err.code or 500))

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover - defensive
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err), 500))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
