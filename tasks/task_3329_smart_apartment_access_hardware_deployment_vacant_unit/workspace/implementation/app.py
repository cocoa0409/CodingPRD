"""SmartRent access-hardware API — application entry point."""

import os

from flask import Flask, request

from errors import ApiError
from response import error_response

RECOGNIZED_ROLES = (
    "PlatformAdmin",
    "PropertyManager",
    "HardwareTechnician",
    "MaintenanceTechnician",
    "LeasingAgent",
    "Resident",
)

API_PREFIX = "/smart-rent"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from services.attach import attach_all

    from routes import api

    attach_all()
    app.register_blueprint(api)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_not_found(exc):
        return error_response(
            "ERR_NOT_FOUND", "No route matches %s" % request.path, 404
        )

    @app.errorhandler(405)
    def _handle_method_not_allowed(exc):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED",
            "Method %s is not allowed on %s" % (request.method, request.path),
            405,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response(
            "ERR_INTERNAL", "Unhandled server error: %s" % exc, 500
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )