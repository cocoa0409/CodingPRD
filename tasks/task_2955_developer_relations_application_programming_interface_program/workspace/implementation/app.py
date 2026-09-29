"""Developer Relations API Programme — Flask application factory and entrypoint.

State lives entirely in memory: every process start is a clean programme with
no developers, no products and a logical clock reading 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import DEFAULT_MESSAGES, ERROR_STATUS, ApiError
from response import error_response
from routes.applications import bp as applications_bp
from routes.assignments import bp as assignments_bp
from routes.catalog import bp as catalog_bp
from routes.developers import bp as developers_bp
from routes.feedback import bp as feedback_bp
from routes.leases import bp as leases_bp
from routes.support import bp as support_bp
from routes.system import bp as system_bp
from routes.violations import bp as violations_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in (
        developers_bp,
        catalog_bp,
        applications_bp,
        assignments_bp,
        leases_bp,
        violations_bp,
        support_bp,
        feedback_bp,
        system_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(error):
        status = ERROR_STATUS.get(error.error_id, 400)
        message = error.message or DEFAULT_MESSAGES.get(
            error.error_id, "The request could not be completed."
        )
        return error_response(error.error_id, message, status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(error):
        if error.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "No such resource path.", 404
            )
        if error.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST",
                "That method is not allowed on this path.",
                405,
            )
        if error.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", error.description or "Request failed.", error.code
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(error):  # pragma: no cover - defensive only
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
