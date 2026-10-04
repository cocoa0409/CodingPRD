"""Entry point: Flask app assembly, error handlers, and the dev server.

Listens on PORT (default 10000), bound to 0.0.0.0, in the foreground.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from routes import ALL_BLUEPRINTS
from util import error_body


def create_app():
    app = Flask(__name__, static_folder=None)
    try:  # Flask >= 2.2 only; key order is irrelevant to JSON semantics
        app.json.sort_keys = False
    except AttributeError:
        pass

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return (
            jsonify(error_body("ERR_NOT_FOUND", "resource not found")),
            404,
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return (
            jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "method not allowed")),
            405,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return jsonify(error_body(exc.error_id, exc.message)), exc.http_status
        app.logger.exception("unexpected error: %s", exc)
        return (
            jsonify(error_body("ERR_INTERNAL", "internal server error")),
            500,
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
