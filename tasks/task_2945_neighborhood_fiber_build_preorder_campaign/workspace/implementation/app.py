"""Neighborhood Fiber Build & Preorder Campaign API.

All state lives in process memory and is empty on every boot: nothing is seeded,
nothing is persisted, and re-invoking start.sh wipes every byte of it.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return envelope.error_body(error.error_id, error.message), error.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        status = error.code or 500
        if status == 404:
            error_id = "ERR_INVALID_REQUEST"
            status = 404
        elif status == 405:
            error_id = "ERR_INVALID_REQUEST"
        elif status == 415:
            error_id = "ERR_INVALID_REQUEST"
            status = 400
        elif status == 400:
            error_id = "ERR_INVALID_REQUEST"
        else:
            error_id = "ERR_INVALID_REQUEST"
        return envelope.error_body(error_id, error.description or "request failed"), status

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return envelope.error_body("ERR_INVALID_REQUEST", str(error)), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
