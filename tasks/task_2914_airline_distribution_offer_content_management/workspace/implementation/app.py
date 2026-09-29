"""Airline Distribution Offers API — application entry point.

State lives in process memory only (see store.py); nothing is persisted and
nothing is seeded. Every entity is created through the declared endpoints.
"""
import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from envelope import respond_error  # noqa: E402
from errors import ApiError, ERROR_HTTP  # noqa: E402
from routes import (agreements, certifications, channels, clock, contracts,  # noqa: E402
                    fares, offers, orders, partners, servicing)

BLUEPRINTS = (
    clock.bp,
    channels.bp,
    partners.bp,
    fares.bp,
    agreements.bp,
    contracts.bp,
    offers.bp,
    orders.bp,
    servicing.bp,
    certifications.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return respond_error("ERR_INVALID_REQUEST",
                                 "No such route on this service.", 404)
        if status == 405:
            return respond_error("ERR_INVALID_REQUEST",
                                 "Method not allowed on this route.", 405)
        if status < 500:
            return respond_error("ERR_INVALID_REQUEST",
                                 exc.description or "Malformed request.", 400)
        return respond_error("ERR_INTERNAL", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return respond_error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
