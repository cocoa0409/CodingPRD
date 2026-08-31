"""CERT Training Program API — entry point.

Storage is in-memory only and starts EMPTY on every boot; nothing is seeded.
"""
from __future__ import annotations

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from store import store
from web import error_response

import routes_core
import routes_training
import routes_credentials
import routes_ops


class SerialMiddleware(object):
    """Serialise request handling so cascades never interleave."""

    def __init__(self, wsgi_app, lock):
        self.wsgi_app = wsgi_app
        self.lock = lock

    def __call__(self, environ, start_response):
        with self.lock:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_training.bp)
    app.register_blueprint(routes_credentials.bp)
    app.register_blueprint(routes_ops.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 405:
            return error_response(ApiError("ERR_INVALID_REQUEST",
                                           "Method not allowed for this path.", 405))
        if err.code == 404:
            return error_response(ApiError("ERR_INVALID_REQUEST",
                                           "No such endpoint.", 404))
        if err.code == 400:
            return error_response(ApiError("ERR_INVALID_REQUEST",
                                           "Malformed request."))
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err), err.code or 400))

    @app.errorhandler(Exception)
    def _unexpected(err):  # pragma: no cover - safety net
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err), 500))

    app.wsgi_app = SerialMiddleware(app.wsgi_app, store.lock)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False, debug=False)
