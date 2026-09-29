"""Hvac Filter Subscription Resident Benefits API.

The store is purely in-memory and starts completely empty on every boot: every
entity is created by the client through the declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import (cases, catalog, claims, clock_route, entitlements,
                    properties, residents, shipments, subscriptions, transfers,
                    units)

BLUEPRINTS = (clock_route.bp, catalog.bp, properties.bp, units.bp, residents.bp,
              subscriptions.bp, shipments.bp, cases.bp, entitlements.bp,
              claims.bp, transfers.bp)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            return envelope.error_response("ERR_INVALID_REQUEST",
                                           "no such route", 404)
        if status == 405:
            return envelope.error_response("ERR_INVALID_REQUEST",
                                           "method not allowed", 405)
        if status in (400, 415):
            return envelope.error_response(
                "ERR_INVALID_REQUEST", "the request body could not be read", 400)
        return envelope.error_response("ERR_INVALID_REQUEST",
                                       exc.description or "request failed", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return envelope.error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
                     threaded=True)
