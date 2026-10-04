"""Entry point for the rating-agency API server.

The process is the store: every boot starts with an empty system.  Nothing is
seeded here or anywhere else at import time — the only fixture is the logical
clock's documented default instant, which lives in db.Store.
"""

import os
import traceback

from flask import Flask, request

from auth import resolve_actor  # noqa: F401  (imported for its side effects on errors)
from db import db
from errors import ApiError
from response import error_body

API_PREFIX = "/rating-agency"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import committees, core, requests, surveillance, teams

    for module in (core, requests, teams, committees, surveillance):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_body(
            "ERR_RESOURCE_NOT_FOUND",
            "The requested resource does not exist.",
            404,
        )

    @app.errorhandler(405)
    def handle_bad_method(_exc):
        return error_body(
            "ERR_RESOURCE_NOT_FOUND",
            "The requested resource does not exist.",
            404,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc()
        return error_body(
            "ERR_INVALID_STATE",
            "The request could not be processed.",
            409,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)