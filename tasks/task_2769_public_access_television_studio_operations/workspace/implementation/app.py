"""Public Access TV Ops API -- Flask application entry point.

Storage is in-memory only and starts empty on every boot; every entity is
created by an API caller.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    archive,
    channels,
    clock,
    courses,
    crew,
    damage,
    funding,
    producers,
    programs,
    reservations,
    resources,
    series,
    slots,
)

BLUEPRINTS = (
    clock.bp,
    producers.bp,
    courses.bp,
    series.bp,
    programs.bp,
    channels.bp,
    slots.bp,
    crew.bp,
    resources.bp,
    reservations.bp,
    damage.bp,
    funding.bp,
    archive.bp,
)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error_response("ERR_NOT_FOUND", "No such route", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return response.error_response(
            "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this route", 405
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error_response("ERR_INVALID_REQUEST", "Malformed request", 400)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
