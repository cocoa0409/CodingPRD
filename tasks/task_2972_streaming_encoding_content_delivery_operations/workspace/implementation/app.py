"""Streaming Encoding & Delivery Operations API.

Every boot starts from a completely empty in-memory catalogue: nothing is seeded,
preloaded or hardcoded except the logical clock's declared default of
2026-08-01T00:00:00Z (PRD 2.5).
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import assets, delivery, drm, jobs, ladders, live, system, titles


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for module in (system, titles, assets, ladders, drm, delivery, live, jobs):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        # Unroutable paths and unsupported methods still answer in the envelope
        # of PRD 2.2; the ladder itself never produces these.
        if err.code == 404:
            return error_response(ApiError("ERR_TITLE_NOT_FOUND", "no such route"))
        if err.code == 405:
            return error_response(ApiError("ERR_INVALID_REQUEST", "method not allowed"))
        if err.code in (400, 415):
            return error_response(ApiError("ERR_INVALID_REQUEST", "malformed request"))
        return error_response(ApiError("ERR_INVALID_REQUEST", err.description or "error"))

    @app.errorhandler(Exception)
    def _unexpected(err):
        if isinstance(err, (ApiError, HTTPException)):
            raise err
        return error_response(ApiError("ERR_INVALID_REQUEST", "unexpected failure"))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
