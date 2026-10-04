"""Salaried Agent Model & Customer-Ratio Assignment API — entry point.

The store starts empty on every boot. Nothing is seeded, preloaded or
hardcoded; every entity is created through a declared endpoint.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_REGION_NOT_FOUND", "No resource matches the requested path.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed on this path.", 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)