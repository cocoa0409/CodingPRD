"""Child Care Licensing Compliance API — application entry point.

Storage is in-memory only and nothing is seeded: every entity is created
through the API itself.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import amendments as amendments_routes
from routes import caps as caps_routes
from routes import complaints as complaints_routes
from routes import config as config_routes
from routes import enforcement as enforcement_routes
from routes import inspections as inspections_routes
from routes import postings as postings_routes
from routes import providers as providers_routes
from routes import reports as reports_routes
from routes import rosters as rosters_routes
from routes import staff as staff_routes
from routes import violations as violations_routes

BLUEPRINTS = (
    config_routes.bp,
    providers_routes.bp,
    staff_routes.bp,
    rosters_routes.bp,
    inspections_routes.bp,
    violations_routes.bp,
    complaints_routes.bp,
    reports_routes.bp,
    caps_routes.bp,
    enforcement_routes.bp,
    amendments_routes.bp,
    postings_routes.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return envelope.error(
                "ERR_INVALID_REQUEST", "No route matches the requested path.", 404
            )
        if exc.code == 405:
            return envelope.error(
                "ERR_INVALID_REQUEST", "The method is not allowed on this path.", 405
            )
        if exc.code == 400:
            return envelope.error(
                "ERR_INVALID_REQUEST", "The request body is malformed.", 400
            )
        return envelope.error("ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return envelope.error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=True,
        use_reloader=False,
    )
