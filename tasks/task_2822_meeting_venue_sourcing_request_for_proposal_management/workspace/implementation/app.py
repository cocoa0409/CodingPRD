"""Meeting Venue Sourcing & RFP Management API.

Entry point: registers every blueprint, installs the envelope-shaped error
handlers and serialises requests through one lock so the in-memory store stays
consistent.  Nothing is seeded: the store starts empty on every boot.
"""
import os
import threading

from flask import Flask, g

import response
from errors import ERROR_STATUS, ApiError
from routes import (
    benchmarks,
    clock_routes,
    contracts,
    events,
    inspections,
    proposals,
    reports,
    rfps,
    shortlist,
    venues,
)

_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        clock_routes,
        benchmarks,
        venues,
        events,
        shortlist,
        inspections,
        rfps,
        proposals,
        contracts,
        reports,
    ):
        app.register_blueprint(module.bp)

    @app.before_request
    def _serialize_request():
        _LOCK.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release_request(exc=None):
        if g.pop("_holds_lock", False):
            try:
                _LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error(
            "ERR_NOT_FOUND", "The requested resource does not exist",
            ERROR_STATUS["ERR_NOT_FOUND"],
        )

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return response.error(
            "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this path",
            ERROR_STATUS["ERR_METHOD_NOT_ALLOWED"],
        )

    @app.errorhandler(400)
    def _bad_request(exc):
        return response.error(
            "ERR_INVALID_REQUEST", "The request body could not be parsed",
            ERROR_STATUS["ERR_INVALID_REQUEST"],
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return response.error(
            "ERR_INTERNAL", "Unexpected server error",
            ERROR_STATUS["ERR_INTERNAL"],
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
