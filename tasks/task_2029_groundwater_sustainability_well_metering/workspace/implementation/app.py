"""Groundwater Sustainability & Well Metering Program API — Flask entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response("ERR_NOT_FOUND", "The requested path does not exist", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        return error_response("ERR_INVALID_REQUEST", e.description, e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        app.logger.exception(e)
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
