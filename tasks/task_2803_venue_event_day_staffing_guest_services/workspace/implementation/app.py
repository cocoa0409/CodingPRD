"""Venue Event-Day Staffing and Guest Services API — process entry point.

State lives entirely in module-level dicts, so every fresh process starts empty
with the logical clock at its declared default.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
import routes_access
import routes_events
import routes_guest
import routes_staffing
import routes_work
import routes_workforce


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_events.bp)
    app.register_blueprint(routes_staffing.bp)
    app.register_blueprint(routes_workforce.bp)
    app.register_blueprint(routes_work.bp)
    app.register_blueprint(routes_guest.bp)
    app.register_blueprint(routes_access.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return respond_error(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return respond_error(
                "ERR_VALIDATION_FAILED",
                "The method is not allowed for this path.",
                405,
            )
        if exc.code in (400, 415):
            return respond_error(
                "ERR_VALIDATION_FAILED",
                "The request body could not be read as JSON.",
                422,
            )
        return respond_error(
            "ERR_VALIDATION_FAILED", exc.description or "Request refused.", exc.code
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return respond_error("ERR_INTERNAL", "%s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
