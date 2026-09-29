"""Brand Re-Commerce: Resale-as-a-Service — application entry point.

All state lives in plain in-memory dicts, so a fresh process starts with an
empty programme: every entity is created by callers through the endpoints
below.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import r_config
import r_credit
import r_market
import r_orders
import r_refurb
import r_reports
import r_tradein
from envelope import error_response
from errors import ERROR_HTTP, DEFAULT_MESSAGES, ApiError

PREFIX = "/recommerce"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (r_config, r_tradein, r_refurb, r_market, r_orders, r_credit, r_reports):
        app.register_blueprint(module.bp, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", DEFAULT_MESSAGES.get("ERR_NOT_FOUND", "Not found."), 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                DEFAULT_MESSAGES.get("ERR_METHOD_NOT_ALLOWED", "Method not allowed."),
                405,
            )
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 422)
        status = exc.code if exc.code in ERROR_HTTP.values() else (exc.code or 500)
        return error_response("ERR_INTERNAL", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "An unexpected internal error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
