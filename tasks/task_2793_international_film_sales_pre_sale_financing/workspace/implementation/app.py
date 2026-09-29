"""International film sales and pre-sale financing service.

Storage is in-memory only and starts completely empty on every boot: the
implementation encodes the system, never the data.
"""
from __future__ import annotations

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import api_contracts
import api_films
import api_finance
import api_markets
import api_territories
from envelope import error
from errors import DEFAULT_MESSAGE, ApiError

PREFIX = "/film-sales"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        api_films,
        api_territories,
        api_markets,
        api_contracts,
        api_finance,
    ):
        app.register_blueprint(module.bp, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error(
                "ERR_INVALID_REQUEST",
                "The method is not allowed for this resource.",
                405,
            )
        if exc.code and 400 <= exc.code < 500:
            return error(
                "ERR_INVALID_REQUEST",
                DEFAULT_MESSAGE.get("ERR_INVALID_REQUEST", "Malformed request."),
                exc.code,
            )
        return error("ERR_INTERNAL", "Internal server error.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
