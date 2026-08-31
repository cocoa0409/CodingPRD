"""Bearing & Power-Transmission Rebuild API — entry point.

Storage is in-memory only and starts EMPTY on every boot; no entity is seeded.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import store
from errors import ApiError
from response import error

import routes_bench
import routes_core
import routes_inspect
import routes_orders
import routes_ref
import routes_service


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_ref.bp)
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_inspect.bp)
    app.register_blueprint(routes_bench.bp)
    app.register_blueprint(routes_service.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error("ERR_INVALID_REQUEST", "Unknown route", 404)
        if exc.code == 405:
            return error("ERR_INVALID_REQUEST", "Method not allowed", 405)
        if exc.code in (400, 415):
            return error("ERR_INVALID_REQUEST", "Malformed request", 400)
        return error("ERR_INVALID_REQUEST", exc.description or "Request failed", exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover
        app.logger.exception("unhandled error")
        return error("ERR_INVALID_REQUEST", str(exc), 500)

    @app.before_request
    def _lock():
        store.LOCK.acquire()
        g._store_locked = True

    @app.teardown_request
    def _unlock(exc=None):
        if getattr(g, "_store_locked", False):
            g._store_locked = False
            try:
                store.LOCK.release()
            except RuntimeError:
                pass

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
