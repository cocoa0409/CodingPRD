"""Entry point: Flask application factory, error envelope and route wiring.

The store is created empty by store.py and nothing here seeds it: every entity a
test needs is built through the declared API surface.
"""

import os
import traceback

from flask import Flask

from envelope import failure
from errors import ApiError
from routes import register_all


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_all(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return failure(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return failure(
            "ERR_INVALID_REQUEST", "No route matches the requested path.", 404
        )

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return failure(
            "ERR_INVALID_REQUEST", "The method is not allowed for this path.", 405
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):
        if isinstance(exc, ApiError):
            return failure(exc.error_id, exc.message, exc.http_status)
        traceback.print_exc()
        return failure("ERR_INVALID_REQUEST", "Unhandled request: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
