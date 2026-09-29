"""Audio Post-Production & Sound Design API — entry point.

The in-memory store starts completely empty on every boot: nothing is seeded,
preloaded or hardcoded here or in any imported module.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.adr import bp as adr_bp
from routes.bookings import bp as bookings_bp
from routes.deliverables import bp as deliverables_bp
from routes.facility import bp as facility_bp
from routes.projects import bp as projects_bp
from routes.stems import bp as stems_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(facility_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(stems_bp)
    app.register_blueprint(adr_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(deliverables_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_REFERENCE_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The HTTP method is not allowed for this path.", 405)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Invalid request.", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return response.error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
