"""Brokered Deposit Listing Service Funding Compliance API.

In-memory only: every store starts empty on every boot and nothing is seeded.
The harness relaunches this process before each test, so all state a test needs
is built through the declared API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import brokers, classifications, clock, exceptions, filings, \
    institutions, limits, maturity, placements, plans, programs, ratecaps

BLUEPRINTS = (
    clock.bp,
    institutions.bp,
    ratecaps.bp,
    brokers.bp,
    exceptions.bp,
    programs.bp,
    classifications.bp,
    placements.bp,
    limits.bp,
    plans.bp,
    filings.bp,
    maturity.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "No such route.", 404)
        if exc.code == 405:
            return response.error("ERR_NOT_FOUND",
                                  "Method not allowed for this route.", 405)
        if exc.code in (400, 415):
            return response.error("ERR_INVALID_REQUEST",
                                  "The request body could not be parsed.", 400)
        return response.error("ERR_INVALID_REQUEST", exc.description or "Bad request.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", exc)
        return response.error("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
