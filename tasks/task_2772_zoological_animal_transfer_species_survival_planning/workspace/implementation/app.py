"""Zoological Transfer & Species Survival Planning API -- entry point.

The store is in-memory and starts completely empty on every boot: no entity is
seeded, preloaded or hardcoded here or in any module imported below.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, ERROR_STATUS, error_response
from routes import (agreements, animals, bookings, clock, documents, institutions, introductions,
                    programs, quarantine, recommendations, submissions, tests, veterinarians)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (institutions, programs, veterinarians, animals, recommendations, agreements,
                   documents, tests, quarantine, bookings, introductions, submissions, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", "Unknown resource path.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", "Method not allowed for this path.", 405)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Invalid request.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    assert ERROR_STATUS
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
