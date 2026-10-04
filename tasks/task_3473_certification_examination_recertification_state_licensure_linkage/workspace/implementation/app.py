"""EMS Certification Registry API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot;
all domain time reads the logical clock (default 2026-09-01T00:00:00Z).
"""

import os
import traceback

from flask import Flask

from envelope import error_body
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_body(err)

    @app.errorhandler(404)
    def _handle_404(err):
        return error_body(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def _handle_405(err):
        return error_body(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        traceback.print_exc()
        return error_body(ApiError("ERR_INVALID_REQUEST", 500,
                                   "Unexpected server error: %s" % err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
