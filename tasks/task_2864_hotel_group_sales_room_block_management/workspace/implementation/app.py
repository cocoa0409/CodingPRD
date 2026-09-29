"""Hotel Group Sales API — Flask entry point.

State lives in process memory only (core.store); nothing is seeded, persisted or
read from disk, so every fresh process starts with an empty system and the
logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask

from core import ApiError, error_response
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_INVALID_REQUEST",
                              "The HTTP method is not allowed on this route.", 405)

    @app.errorhandler(400)
    def handle_400(_exc):
        return error_response("ERR_INVALID_REQUEST", "The request is malformed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
