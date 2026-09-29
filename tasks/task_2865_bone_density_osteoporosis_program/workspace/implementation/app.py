"""Bone Density and Osteoporosis Program API — in-memory Flask application.

No data is seeded: every entity is created through a declared endpoint, and a
fresh process starts with completely empty collections and the logical clock at
2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.acquisition import bp as acquisition_bp
from routes.devices import bp as devices_bp
from routes.foundation import bp as foundation_bp
from routes.interpretation import bp as interpretation_bp
from routes.scheduling import bp as scheduling_bp
from routes.treatment import bp as treatment_bp

API_PREFIX = "/bone-density"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in (foundation_bp, devices_bp, scheduling_bp, acquisition_bp,
                      interpretation_bp, treatment_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND", "No such resource.", 404))
        if err.code == 405:
            return error_response(
                ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405))
        if err.code == 400:
            return error_response(
                ApiError("ERR_INVALID_REQUEST", "The request body is malformed.", 422))
        if err.code == 415:
            return error_response(
                ApiError("ERR_INVALID_REQUEST", "The request body is malformed.", 422))
        return error_response(
            ApiError("ERR_INTERNAL", err.description or "Unexpected error.",
                     err.code or 500))

    @app.errorhandler(Exception)
    def _unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", str(err), 500))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=False)
