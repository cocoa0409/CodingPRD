"""Kettle Campaign Corps Service Delivery API — application entry point.

Run from ./implementation with `bash start.sh` (or `python3 app.py`).  The
server listens on 0.0.0.0:$PORT (default 10000) in the foreground.

The store is in-memory only and starts completely empty: nothing is seeded,
preloaded or hardcoded here or in any module import path.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import store
from core.blueprint import bp
from core.envelope import error_response
from core.errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Domain modules register their routes on the shared blueprint.
    from domain import (  # noqa: F401
        assistance,
        campaigns,
        collections,
        deployments,
        giving,
        hostsites,
        locations,
        programs,
        reallocation,
        ringers,
        shifts,
        system,
        units,
    )

    app.register_blueprint(bp, url_prefix="/api")

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_RESOURCE_NOT_FOUND"))
        return error_response(ApiError("ERR_INVALID_REQUEST", http_status=err.code or 400))

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover - defensive
        app.logger.exception("unhandled error")
        return error_response(ApiError("ERR_INVALID_REQUEST", "The request could not be processed.", 500))

    @app.route("/health", methods=["GET"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    store.reset()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
