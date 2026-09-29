"""Reverse Logistics Returns Processing Center API — entry point.

The in-memory store starts completely empty on every boot: nothing is seeded,
preloaded or hardcoded here.  The harness relaunches this process through
start.sh before every test, so a fresh process means a fresh, empty world with
the logical clock parked at 2026-08-01T00:00:00.000Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import catalog, clients, dispositions, lines, receipts, refurb, rma


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clients.bp)
    app.register_blueprint(catalog.bp)
    app.register_blueprint(rma.bp)
    app.register_blueprint(receipts.bp)
    app.register_blueprint(lines.bp)
    app.register_blueprint(refurb.bp)
    app.register_blueprint(dispositions.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if err.code == 404:
            return response.error_response(ApiError("ERR_NOT_FOUND"))
        if err.code == 405:
            return response.error_response(ApiError("ERR_METHOD_NOT_ALLOWED"))
        if err.code in (400, 415):
            return response.error_response(
                ApiError("ERR_INVALID_REQUEST", "Request could not be parsed.")
            )
        return response.error_response(
            ApiError("ERR_INTERNAL", err.description, err.code)
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover - defensive
        return response.error_response(ApiError("ERR_INTERNAL", str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=True,
    )
