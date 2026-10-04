"""Donated Medicine Allocation API — Flask entry point."""
import os

from flask import Flask

from common import ApiError, error_response
import routes_core
import routes_alloc
import routes_logistics
import routes_misc


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    routes_core.register(app)
    routes_alloc.register(app)
    routes_logistics.register(app)
    routes_misc.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ApiError("ERR_INVALID_REQUEST", 400, "Malformed request"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
