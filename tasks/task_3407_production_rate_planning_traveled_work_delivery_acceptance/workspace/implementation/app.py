"""Aero Production Rate Delivery API.

A single Flask process holding every record in memory. Nothing is seeded and
nothing is persisted: a fresh boot starts with zero rows and a logical clock
reading exactly 2026-09-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
from routes.aircraft import bp as aircraft_bp
from routes.customers import bp as customers_bp
from routes.delivery import bp as delivery_bp
from routes.escapes import bp as escapes_bp
from routes.negotiations import bp as negotiations_bp
from routes.programs import bp as programs_bp
from routes.reference import bp as reference_bp
from routes.rework import bp as rework_bp
from routes.storage import bp as storage_bp
from routes.suppliers import bp as suppliers_bp
from routes.workforce import bp as workforce_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(workforce_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(aircraft_bp)
    app.register_blueprint(rework_bp)
    app.register_blueprint(escapes_bp)
    app.register_blueprint(delivery_bp)
    app.register_blueprint(storage_bp)
    app.register_blueprint(negotiations_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return respond_error(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if status in (400, 415):
            return respond_error(
                "ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400
            )
        if status == 405:
            return respond_error(
                "ERR_INVALID_REQUEST",
                "The HTTP method is not allowed on this path.",
                405,
            )
        return respond_error(
            "ERR_INTERNAL", exc.description or "Unhandled error.", status
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover -- defensive
        return respond_error("ERR_INTERNAL", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
