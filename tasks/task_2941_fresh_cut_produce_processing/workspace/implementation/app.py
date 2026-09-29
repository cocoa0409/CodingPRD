"""Fresh-Cut Produce Processing API. Flask entry point.

The store is in-memory and starts completely empty on every boot: no entity is
ever seeded, preloaded or hardcoded here (PRD/INSTRUCTION build contract).
"""

import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ERROR_STATUS, ApiError
from routes import clock, growerlots, holds, lines, products, runs, wash


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (products, wash, growerlots, lines, runs, holds, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "That method is not allowed on this path.",
                405,
            )
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        return error_response(
            "ERR_INTERNAL",
            exc.description or "Request failed.",
            exc.code or ERROR_STATUS["ERR_INTERNAL"],
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
        use_reloader=False,
    )
