"""Government Surplus Property Disposal API — application entry point.

The store is in-memory only and starts completely empty on every boot; no
entity is ever seeded, preloaded or hardcoded here.  Tests build all state
through the declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes import (agencies, assets, bidders, clock, finance, invoices, lots,
                    release, screening, transfers, turnins, venues)

MODULES = (
    agencies,
    turnins,
    assets,
    release,
    screening,
    transfers,
    venues,
    lots,
    bidders,
    invoices,
    finance,
    clock,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for module in MODULES:
        module.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error("ERR_INVALID_REQUEST", "Unknown resource path", 404)
        if exc.code == 405:
            return error("ERR_INVALID_REQUEST",
                         "Method not allowed on this path", 405)
        return error("ERR_INVALID_REQUEST", exc.description or "Bad request",
                     exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error("ERR_INTERNAL", "Unexpected server error: " + str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
