"""AIS Inspection & Decontamination API -- Flask entry point.

The store is purely in-memory and starts completely empty on every boot: no
entity is ever seeded, preloaded or hardcoded here. Tests build all state
through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import (campaigns, clock, decon, detection, inspectors, quarantine,
                    records, registry, stations, water_bodies)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (water_bodies, stations, inspectors, registry, records,
                   decon, quarantine, detection, campaigns, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "The requested route does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST",
                "The HTTP method is not allowed on this route.", 405,
            )
        if exc.code and 400 <= exc.code < 500:
            return error_response(
                "ERR_INVALID_REQUEST", exc.description or "Bad request.", exc.code
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Server error.",
            exc.code or 500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
