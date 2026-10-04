"""Wetland Permit Review & Compensatory Mitigation API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000) per INSTRUCTION.md. All state is
in-memory and starts empty on every process boot.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import applicants_sites, applications, banks, clock, enforcement, \
    jds_appeals, mitigation, permits, review


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (applicants_sites, jds_appeals, applications, review,
                   mitigation, banks, permits, enforcement, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error)

    @app.errorhandler(404)
    def handle_not_found(error):
        return error_response(
            ApiError("ERR_NOT_FOUND", 404, "Resource or route not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", 405,
                     "Method not allowed for this route"))

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return error_response(
            ApiError("ERR_INTERNAL", 500, "Internal server error: %s"
                     % type(error).__name__))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
