"""Grief & Bereavement Support API — entry point.

In-memory storage only; the store starts empty on every boot.
"""

import os
import threading

from flask import Flask, jsonify

from core.envelope import error_response
from core.errors import ApiError
from routes import BLUEPRINTS


_WRITE_LOCK = threading.RLock()


class SerializingMiddleware(object):
    """Serialise requests so every cascade lands atomically."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with _WRITE_LOCK:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_INVALID_REQUEST", "Unknown route.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    app.wsgi_app = SerializingMiddleware(app.wsgi_app)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
