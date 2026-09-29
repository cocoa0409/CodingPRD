"""Global Payroll Aggregation API.

All state lives in process memory (see store.py) and vanishes when the process
exits. Nothing is seeded at startup: every entity is built through the API.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from common import ApiError
from response import error_response
from routes import (
    clock,
    cycles,
    engagements,
    estate,
    evidence,
    filings,
    funding,
    gtn,
    incidents,
    inputs,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        clock,
        estate,
        engagements,
        cycles,
        inputs,
        gtn,
        funding,
        filings,
        incidents,
        evidence,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "The requested resource does not exist.", 404
            )
        if status == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "The method is not allowed for this path.", 405
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "The request could not be processed.", status
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
