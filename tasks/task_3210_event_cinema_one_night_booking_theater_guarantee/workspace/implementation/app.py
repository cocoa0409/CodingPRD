"""Event Cinema One-Night Booking & Theater Guarantee API.

A single Flask process holding every record in memory. Nothing is seeded and
nothing is persisted: a fresh boot starts with twelve empty collections and a
logical clock reading exactly 2026-09-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
from routes.bookings import bp as bookings_bp
from routes.entities import bp as entities_bp
from routes.operations import bp as operations_bp
from routes.screenings import bp as screenings_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(entities_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(screenings_bp)
    app.register_blueprint(operations_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return respond_error(
                "ERR_INVALID_REQUEST", "The requested path does not exist.", 404
            )
        if status == 405:
            return respond_error(
                "ERR_INVALID_REQUEST",
                "The HTTP method is not allowed on this path.",
                405,
            )
        if status in (400, 415):
            return respond_error(
                "ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400
            )
        return respond_error(
            "ERR_INVALID_REQUEST", exc.description or "Unhandled request error.", status
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover -- defensive
        return respond_error(
            "ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)