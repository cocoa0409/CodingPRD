"""Catalog Circulation Planning API — Flask application factory and entrypoint.

Storage is in-memory only and no entity data is ever seeded: every row in the
service is created through a declared endpoint.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import config, drops, lines, measure, plans, rentals, segments

PREFIX = "/catalog-circulation"

BLUEPRINTS = (
    config.bp,
    segments.bp,
    rentals.bp,
    plans.bp,
    drops.bp,
    lines.bp,
    measure.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_response(
            "ERR_INVALID_REQUEST", "Request body must be valid JSON.", 422
        )

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path.", 405
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
