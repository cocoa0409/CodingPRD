"""Landfill Gas & RNG Operations API - entry point."""

import functools
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import store
from envelope import error_response
from errors import ApiError
from routes import (
    attributes,
    batches,
    contracts,
    downtime,
    nominations,
    plants,
    reports,
    royalty,
    sites,
    wells,
    workorders,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (
        sites,
        wells,
        workorders,
        plants,
        downtime,
        contracts,
        nominations,
        batches,
        attributes,
        reports,
        royalty,
    ):
        app.register_blueprint(module.bp)

    # Serialise request handling: the store is a plain in-memory structure.
    def locked(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            with store.LOCK:
                return view(*args, **kwargs)

        return wrapper

    for name, view in list(app.view_functions.items()):
        app.view_functions[name] = locked(view)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        return error_response(
            "ERR_VALIDATION",
            exc.description or "The request could not be routed.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_VALIDATION", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
