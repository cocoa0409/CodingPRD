"""Wire & Cable Distribution API.

Entry point: registers the route blueprints and the standard error handlers.
Storage is in-memory only and starts completely empty on every boot -- nothing
is seeded, preloaded or hardcoded.
"""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import allocations, catalog, delivery, orders, quotes, reels


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(catalog.bp)
    app.register_blueprint(reels.bp)
    app.register_blueprint(quotes.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(allocations.bp)
    app.register_blueprint(delivery.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path.", 405)
        if exc.code in (400, 415):
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request payload is malformed.", 422)
        return response.error_response(
            "ERR_INTERNAL", exc.description or "Unexpected error.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


class _SerializedWSGI:
    """Cascades are immediate and synchronous; serialising request dispatch keeps
    every multi-step mutation atomic under concurrent clients."""

    def __init__(self, wsgi_app):
        self._wsgi_app = wsgi_app
        self._lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self._lock:
            return self._wsgi_app(environ, start_response)


app.wsgi_app = _SerializedWSGI(app.wsgi_app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
