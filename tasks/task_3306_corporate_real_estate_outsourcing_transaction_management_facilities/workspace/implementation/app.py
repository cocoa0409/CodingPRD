import os

from flask import Flask, request

from core.errors import ApiError
from core.response import error_response

import routes.accounts  # noqa: F401
import routes.leases  # noqa: F401
import routes.transactions  # noqa: F401
import routes.brokers  # noqa: F401
import routes.facilities  # noqa: F401
import routes.consolidation  # noqa: F401
import routes.governance  # noqa: F401
import routes.licenses  # noqa: F401
import routes.transitions  # noqa: F401
import routes.clock  # noqa: F401
from routes.registry import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_RESOURCE_NOT_FOUND",
                              "No route matches the supplied path and method.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_INVALID_REQUEST",
                              "The HTTP method is not supported for this path.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))