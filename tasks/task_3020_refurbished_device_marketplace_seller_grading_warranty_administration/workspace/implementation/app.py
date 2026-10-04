"""Entry point for the refurbished-device marketplace API.

The store starts empty on every boot: nothing here seeds, preloads or registers
any entity.  Every row a test observes was created through a declared endpoint
during that same process lifetime.
"""

import os
import sys

from flask import Flask, request
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import store  # noqa: E402
from errors import ApiError  # noqa: E402
from response import err  # noqa: E402
from routes import (  # noqa: E402
    grading,
    listings,
    scores,
    sellers,
    system,
    tradeins,
    verifications,
    warranties,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    sellers.register(app)
    listings.register(app)
    verifications.register(app)
    warranties.register(app)
    grading.register(app)
    tradeins.register(app)
    scores.register(app)
    system.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return err(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return err("ERR_RESOURCE_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return err("ERR_RESOURCE_NOT_FOUND", "No such endpoint.", 404)
        return err("ERR_INVALID_REQUEST", exc.description or exc.name, exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        app.logger.exception("unhandled error")
        return err("ERR_INVALID_REQUEST", str(exc), 400)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)