"""Duty-Free Retail Operations API.

The store is in-memory and starts completely empty on every boot: nothing is
seeded, preloaded or hardcoded.  Every entity is created by callers through the
declared endpoints.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.agreements import bp as agreements_bp
from routes.audits import bp as audits_bp
from routes.bonded import bp as bonded_bp
from routes.clock_routes import bp as clock_bp
from routes.estate import bp as estate_bp
from routes.itineraries import bp as itineraries_bp
from routes.preorders import bp as preorders_bp
from routes.sales import bp as sales_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in (clock_bp, estate_bp, bonded_bp, itineraries_bp, sales_bp,
                      preorders_bp, agreements_bp, audits_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return response.error(
                "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this resource.", 405
            )
        if exc.code in (400, 415):
            return response.error("ERR_INVALID_REQUEST", "The request payload is malformed.", 422)
        return response.error(
            "ERR_INTERNAL", exc.description or "Unexpected error.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
