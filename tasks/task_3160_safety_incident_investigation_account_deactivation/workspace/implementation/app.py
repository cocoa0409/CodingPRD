"""Entry point: error handlers and route registration.

The store is constructed empty at import time and is never seeded; the server's
startup logical time is the fixed 2026-09-01T00:00:00Z instant and real
wall-clock time is never consulted.
"""

import os
import traceback

from flask import Flask

from errors import ApiError
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    from routes import register_blueprints
    register_blueprints(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body, status = error_body(exc.error_id, exc.message, exc.http_status)
        return body, status

    @app.errorhandler(404)
    def handle_not_found(exc):
        body, status = error_body("ERR_RESOURCE_NOT_FOUND",
                                  "The requested route does not exist.", 404)
        return body, status

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        body, status = error_body("ERR_RESOURCE_NOT_FOUND",
                                  "The method is not allowed on this route.", 405)
        return body, status

    @app.errorhandler(500)
    def handle_server_error(exc):
        traceback.print_exc()
        body, status = error_body("ERR_INVALID_STATE",
                                  "The request could not be completed.", 500)
        return body, status

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc()
        body, status = error_body("ERR_INVALID_STATE", str(exc), 500)
        return body, status

    @app.route("/", methods=["GET"])
    def root():
        body, status = error_body("ERR_RESOURCE_NOT_FOUND",
                                  "The requested route does not exist.", 404)
        return body, status

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))