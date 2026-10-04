"""Application entry point: blueprint registration, error handlers, launcher."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response

import routes_additions
import routes_devices
import routes_lines
import routes_migration
import routes_port
import routes_promo
import routes_protection
import routes_reservations
import routes_system


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        routes_system,
        routes_lines,
        routes_port,
        routes_migration,
        routes_devices,
        routes_reservations,
        routes_additions,
        routes_protection,
        routes_promo,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_INVALID_REQUEST", "No such endpoint or resource.", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Method not allowed for this endpoint.", 405)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Malformed request.", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)