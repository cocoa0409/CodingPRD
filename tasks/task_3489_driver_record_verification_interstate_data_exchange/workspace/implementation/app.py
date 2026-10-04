"""Driver Record Exchange API -- application entry point.

Flask app factory, blueprint registration, and error handling. Boots with an
empty in-memory store and the logical clock at 2026-09-01T00:00:00Z; nothing
is seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import store
from errors import ApiError
from routes_certification import bp as certification_bp
from routes_clock import bp as clock_bp
from routes_convictions import bp as convictions_bp
from routes_drivers import bp as drivers_bp
from routes_fees import bp as fees_bp
from routes_jurisdictions import bp as jurisdictions_bp
from routes_licenses import bp as licenses_bp
from routes_titles import bp as titles_bp
from routes_transfers import bp as transfers_bp

BLUEPRINTS = (
    clock_bp,
    jurisdictions_bp,
    certification_bp,
    drivers_bp,
    convictions_bp,
    licenses_bp,
    transfers_bp,
    titles_bp,
    fees_bp,
)


def create_app():
    app = Flask(__name__)
    store.db.reset()
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, HTTPException):
            return exc
        if isinstance(exc, ApiError):
            return response.error_response(exc)
        app.logger.exception("unhandled error")
        return response.error_response(
            ApiError("ERR_INTERNAL", 500, "internal server error: %s" % exc))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
