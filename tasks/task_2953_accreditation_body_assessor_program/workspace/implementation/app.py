"""Accreditation Body Assessor Program API.

A single-process Flask application whose entire state lives in Python dicts. No row
is seeded at import time or at boot: the test suite builds every entity through the
declared endpoints.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes
from envelope import failure
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in routes.BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _reset_touched():
        g.touched = set()

    @app.errorhandler(ApiError)
    def _api_error(error):
        return failure(error.error_id, error.message, error.status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return failure("ERR_NOT_FOUND", "The requested path does not exist.", 404)
        if error.code == 405:
            return failure("ERR_METHOD_NOT_ALLOWED",
                           "The method is not allowed for this path.", 405)
        if error.code == 400:
            return failure("ERR_INVALID_REQUEST", "The request body is not valid JSON.", 400)
        return failure("ERR_INVALID_REQUEST", error.description or "Request rejected.",
                       error.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(error):
        return failure("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
