"""Timeshare Exchange Network Operations API.

A single Flask process holding every row in memory.  Nothing is seeded: the
store boots completely empty and every row the API reports was created by a
caller through one of the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.config import bp as config_bp
from routes.deposits import bp as deposits_bp
from routes.disputes import bp as disputes_bp
from routes.exchange import bp as exchange_bp
from routes.members import bp as members_bp
from routes.resorts import bp as resorts_bp
from routes.runs import bp as runs_bp

API_PREFIX = "/exchange-network"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in (config_bp, resorts_bp, members_bp, deposits_bp,
                      exchange_bp, runs_bp, disputes_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Request body or query parameters failed shape validation.", 400)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "That method is not allowed on this route.", 405)

    @app.errorhandler(415)
    def handle_unsupported_media(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Request body or query parameters failed shape validation.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return error_response("ERR_INVALID_REQUEST", exc.description or exc.name,
                                  exc.code or 400)
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
