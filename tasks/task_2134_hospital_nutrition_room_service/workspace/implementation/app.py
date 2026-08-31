"""Hospital Nutrition Room Service API -- application entry point.

The data store is in-memory only and starts EMPTY on every boot: no entity is
seeded, preloaded or hardcoded here.  Every row a test needs is created through
the declared API surface.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import api
from errors import ApiError
from routes import (catalog, clock, consults, diet_orders, holds, lines,
                    meal_orders, meal_periods, patients, surveys, tray_line,
                    wards)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clock.bp)
    app.register_blueprint(catalog.rules_bp)
    app.register_blueprint(catalog.items_bp)
    app.register_blueprint(consults.bp)
    app.register_blueprint(consults.sup_bp)
    app.register_blueprint(diet_orders.bp)
    app.register_blueprint(holds.bp)
    app.register_blueprint(lines.bp)
    app.register_blueprint(lines.sub_bp)
    app.register_blueprint(meal_orders.bp)
    app.register_blueprint(meal_periods.bp)
    app.register_blueprint(patients.bp)
    app.register_blueprint(surveys.bp)
    app.register_blueprint(tray_line.bp)
    app.register_blueprint(wards.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return api.error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if err.code == 404:
            return api.error_response(ApiError("ERR_NOT_FOUND", "Resource not found."))
        if err.code == 405:
            return api.error_response(
                ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed."))
        if err.code == 400:
            return api.error_response(
                ApiError("ERR_INVALID_REQUEST", "The request is malformed."))
        return api.error_response(
            ApiError("ERR_INVALID_REQUEST", err.description or "Request failed",
                     http_status=err.code))

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover - safety net
        app.logger.exception("Unhandled error")
        return api.error_response(
            ApiError("ERR_INVALID_REQUEST", "Unexpected server error.",
                     http_status=500))

    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True, debug=False,
                    use_reloader=False)
