"""Dough Facility Replenishment API -- Flask entry point.

All state lives in process memory (see db.py): every invocation of start.sh
begins with an empty store. No business entity is ever seeded at startup; the
logical clock starts at exactly 2026-09-01T00:00:00Z per PRD section 2.5.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import response as resp
from errors import ApiError
from routes import (adjustments, billing, clock, donations, master, orders,
                    plans, routes_stops, schedules)

BLUEPRINTS = (
    clock.bp,
    master.bp,
    adjustments.bp,
    orders.bp,
    plans.bp,
    routes_stops.bp,
    schedules.bp,
    donations.bp,
    billing.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin_request():
        db.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return resp.error_response(err)

    @app.errorhandler(404)
    def _not_found(err):
        return resp.error_response(ApiError("ERR_NOT_FOUND"))

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return resp.error_response(ApiError("ERR_METHOD_NOT_ALLOWED"))

    @app.errorhandler(400)
    def _bad_request(err):
        return resp.error_response(ApiError("ERR_VALIDATION"))

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return resp.error_response(ApiError("ERR_NOT_FOUND"))
        if err.code == 405:
            return resp.error_response(ApiError("ERR_METHOD_NOT_ALLOWED"))
        if err.code and err.code < 500:
            return resp.error_response(ApiError("ERR_VALIDATION"))
        return resp.error_response(ApiError("ERR_INTERNAL"))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return resp.error_response(err)
        app.logger.exception("unhandled error: %s", err)
        return resp.error_response(ApiError("ERR_INTERNAL"))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
