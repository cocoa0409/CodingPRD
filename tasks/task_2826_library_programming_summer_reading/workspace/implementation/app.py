"""Library Programming & Summer Reading API — Flask application entry point.

Storage is process-local and in-memory: every launch starts with an empty
system and a logical clock reading exactly 2026-08-01T00:00:00.000Z.  Nothing
is seeded, nothing is persisted to disk.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from routes import challenges, lifecycle, presenters, programs, reference
from web import error_body

DEFAULT_PORT = 10000


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference.bp)
    app.register_blueprint(programs.bp)
    app.register_blueprint(lifecycle.bp)
    app.register_blueprint(presenters.bp)
    app.register_blueprint(challenges.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", "The request is invalid.")),
            400,
        )

    @app.errorhandler(404)
    def handle_not_found(exc):
        return (
            jsonify(
                error_body("ERR_NOT_FOUND", "The requested resource does not exist.")
            ),
            404,
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return (
            jsonify(
                error_body(
                    "ERR_METHOD_NOT_ALLOWED",
                    "That method is not allowed on this resource.",
                )
            ),
            405,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        app.logger.exception("unhandled error")
        return (
            jsonify(error_body("ERR_INTERNAL", "An unexpected error occurred.")),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
