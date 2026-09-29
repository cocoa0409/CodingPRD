"""Landscape Supply Yard API -- Flask application factory and entry point.

State lives in process memory only (see core.Store) and starts completely
empty on every boot; the test harness relaunches this process per test.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
import routes_accounts
import routes_catalog
import routes_claims
import routes_delivery
import routes_orders
import routes_willcall

BLUEPRINT_MODULES = (
    routes_catalog,
    routes_accounts,
    routes_orders,
    routes_delivery,
    routes_willcall,
    routes_claims,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for module in BLUEPRINT_MODULES:
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return respond_error(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return respond_error("ERR_NOT_FOUND", "Resource not found.", 404)
        if error.code == 405:
            return respond_error("ERR_INVALID_REQUEST",
                                 "Method not allowed on this path.", 405)
        if error.code == 400:
            return respond_error("ERR_INVALID_REQUEST",
                                 "The request could not be parsed.", 400)
        return respond_error("ERR_INVALID_REQUEST",
                             error.description or "Request failed.",
                             error.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(error):
        return respond_error("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
