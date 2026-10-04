"""Entry point for the Member Benefit Bundling API."""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ApiError
from response import error_body
import routes


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return jsonify(error_body(ERR_RESOURCE_NOT_FOUND, "No such endpoint.")), 404
        if exc.code in (400, 405):
            return (
                jsonify(error_body(ERR_INVALID_REQUEST, "The request could not be processed.")),
                exc.code if exc.code == 400 else 405,
            )
        return (
            jsonify(error_body(ERR_INVALID_REQUEST, "The request could not be processed.")),
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return jsonify(error_body(exc.error_id, exc.message)), exc.http_status
        return (
            jsonify(error_body(ERR_INVALID_REQUEST, "The request could not be processed.")),
            400,
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)