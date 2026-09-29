"""Bovine Genetics & Semen Distribution API -- entry point.

The store is in-memory only and starts completely empty on every boot: no
seeding, no preloading, no fixtures. Every entity is created by a caller
through the declared API surface.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import config
import envelope
from errors import ApiError
from routes import (advisory, bookings, certificates, clock, distribution,
                    evaluations, facilities, health, lots, sires)

BLUEPRINTS = [
    clock.bp, facilities.bp, sires.bp, health.bp, bookings.bp, lots.bp,
    evaluations.bp, certificates.bp, distribution.bp, advisory.bp,
]


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=config.API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.error("ERR_RESOURCE_NOT_FOUND", "The requested route does not exist.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return envelope.error("ERR_RESOURCE_NOT_FOUND",
                             "The requested method is not allowed on this route.", 404)

    @app.errorhandler(400)
    def _bad_request(exc):
        return envelope.error("ERR_VALIDATION", "The request body could not be parsed.", 400)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return envelope.error("ERR_VALIDATION", exc.description or "Request rejected.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return envelope.error("ERR_VALIDATION", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
