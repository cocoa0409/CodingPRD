"""Fast-Follow Beauty API — Flask entry point.

Boots with a completely empty in-memory store (no seeding); the logical clock
reads 2026-09-01T00:00:00Z until a PlatformAdmin sets it. start.sh re-runs
this module on every per-test reboot.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core.envelope import error_response
from core.errors import ApiError, err
from routes import register_all


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_all(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response(err("ERR_NOT_FOUND", "route not found"))

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response(err("ERR_METHOD_NOT_ALLOWED", "method not allowed"))

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        if isinstance(e, HTTPException):
            if e.code == 404:
                return error_response(err("ERR_NOT_FOUND", "route not found"))
            if e.code == 405:
                return error_response(err("ERR_METHOD_NOT_ALLOWED", "method not allowed"))
            if e.code is not None and 400 <= e.code < 500:
                return error_response(err("ERR_INVALID_REQUEST", e.name))
        return error_response(err("ERR_INTERNAL", "internal server error"))

    @app.get("/health")
    def _health():
        return jsonify({"status": "ok"}), 200

    @app.get("/")
    def _root():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
