"""Dog Show & Performance Trial Management API.

Flask application factory and error plumbing. The store is in-memory and
starts completely empty on every boot: no entity is ever seeded here.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
import routes_blocks
import routes_classes
import routes_core
import routes_entries
import routes_filings
import routes_panel
import routes_protests
import routes_runs
import routes_shows
import store

API_PREFIX = "/dog-shows"

BLUEPRINTS = (
    routes_core.bp,
    routes_shows.bp,
    routes_panel.bp,
    routes_classes.bp,
    routes_entries.bp,
    routes_blocks.bp,
    routes_runs.bp,
    routes_protests.bp,
    routes_filings.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.before_request
    def _begin_request():
        # One version bump per resource per request.
        store.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "The requested route does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST",
                "The method is not allowed for this route.", 405,
            )
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request body is malformed.", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request rejected.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
        use_reloader=False,
    )
