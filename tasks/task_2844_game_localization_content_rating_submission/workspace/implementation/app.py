"""Game Localization & Content Rating Submission API.

Flask application factory and the global error envelope. Storage is in-memory
only: every entity is created through the API, nothing is seeded at startup.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from db import request_now
from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    @app.before_request
    def _before():
        # one row stamp per request so same-request siblings tie on created_at
        g.row_stamp = None
        g.touched = set()
        request_now()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return error_response(ApiError("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path")
        )

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND", "Resource not found"))
        if err.code == 405:
            return error_response(
                ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path")
            )
        if err.code in (400, 415):
            return error_response(ApiError("ERR_INVALID_REQUEST", str(err.description)))
        return error_response(ApiError("ERR_INTERNAL", str(err.description)))

    @app.errorhandler(Exception)
    def _unhandled(err):
        return error_response(ApiError("ERR_INTERNAL", str(err)))

    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
