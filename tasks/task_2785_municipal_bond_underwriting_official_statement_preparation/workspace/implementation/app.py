"""Municipal Bond Underwriting API - Flask application entry point.

Storage is in-memory only and starts completely empty on every boot.
"""
import os

from flask import Flask

import response
from errors import ApiError
from routes import (
    clock,
    closing,
    deals,
    enhancements,
    orders,
    participants,
    ratings,
    statements,
    syndicate,
    tranches,
    undertakings,
)

BLUEPRINTS = (
    participants.bp,
    deals.bp,
    tranches.bp,
    enhancements.bp,
    statements.bp,
    undertakings.bp,
    ratings.bp,
    syndicate.bp,
    orders.bp,
    closing.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.error_response(error)

    @app.errorhandler(400)
    def handle_bad_request(error):
        return response.error_response(ApiError("ERR_INVALID_REQUEST"))

    @app.errorhandler(404)
    def handle_not_found(error):
        return response.error_response(
            ApiError("ERR_NOT_FOUND", "The requested resource does not exist.")
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return response.error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path.")
        )

    @app.errorhandler(415)
    def handle_unsupported_media(error):
        return response.error_response(ApiError("ERR_INVALID_REQUEST"))

    @app.errorhandler(500)
    def handle_internal(error):
        return response.error_response(
            ApiError("ERR_INTERNAL", "An unexpected error occurred.")
        )

    @app.errorhandler(Exception)
    def handle_uncaught(error):
        if isinstance(error, ApiError):
            return response.error_response(error)
        return response.error_response(
            ApiError("ERR_INTERNAL", "An unexpected error occurred.")
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
