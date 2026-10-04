"""Food Facility Registration & Import Alert Detention API — entry point.

Flask application wiring: blueprint registration and error handlers. All
state lives in db.py module-level stores; nothing is seeded at startup.
"""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError, MESSAGES
import routes_alerts
import routes_clock
import routes_entries
import routes_facilities
import routes_importers
import routes_inspections
import routes_notices
import routes_recalls


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        routes_clock.bp,
        routes_facilities.bp,
        routes_importers.bp,
        routes_notices.bp,
        routes_entries.bp,
        routes_alerts.bp,
        routes_inspections.bp,
        routes_recalls.bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_INVALID_REQUEST", MESSAGES["ERR_INVALID_REQUEST"], 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % err, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
