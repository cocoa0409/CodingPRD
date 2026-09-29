"""Commissary & Exchange Retail Operations API.

Flask application factory, blueprint registration and the envelope-shaped
error handlers.  Storage is in-memory only and completely empty on every boot:
nothing is seeded, preloaded or hardcoded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db as db_module
import routes_catalog
import routes_clock
import routes_delegations
import routes_governance
import routes_patrons
import routes_sales
import routes_special_orders
import routes_stores
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_clock.bp)
    app.register_blueprint(routes_stores.bp)
    app.register_blueprint(routes_patrons.bp)
    app.register_blueprint(routes_delegations.bp)
    app.register_blueprint(routes_catalog.bp)
    app.register_blueprint(routes_sales.bp)
    app.register_blueprint(routes_governance.bp)
    app.register_blueprint(routes_special_orders.bp)

    # One global lock per request keeps every cascade atomic (PRD 2.9).
    @app.before_request
    def _acquire():
        db_module.LOCK.acquire()

    @app.teardown_request
    def _release(_exc=None):
        try:
            db_module.LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "The requested path does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "The method is not allowed on this path.", 405
            )
        if exc.code in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST", "The request body could not be parsed as JSON.", 422
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "The request could not be processed.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_INVALID_REQUEST", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
