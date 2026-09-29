"""Advertising Policy Review API -- Flask entry point.

The store is in-memory only and starts empty on every boot: nothing is seeded,
preloaded or hardcoded here. Every entity a test needs is built through the
declared endpoints of PRD section 4.
"""

import os

from flask import Flask, jsonify

from core import ApiError, error_response
import routes_creatives
import routes_policy
import routes_review

API_PREFIX = "/ad-policy"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.register_blueprint(routes_policy.bp, url_prefix=API_PREFIX)
    app.register_blueprint(routes_creatives.bp, url_prefix=API_PREFIX)
    app.register_blueprint(routes_review.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_NOT_FOUND", 404, "No such route.")

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405,
                              "The method is not allowed for this route.")

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return error_response("ERR_INVALID_REQUEST", 400,
                              "The request could not be parsed.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", 500, "Internal server error.")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
