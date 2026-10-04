"""EEOC Charge Processing API -- Flask entry point.

Wires the per-domain blueprints under the /eeoc prefix, installs the error
handlers that emit the standard error envelope, and runs the dev server in
the foreground on 0.0.0.0:$PORT (default 10000). The store starts empty on
every boot; the logical clock boots to 2026-09-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from helpers import respond_error
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    # Keep JSON key order stable and let the envelope fields appear as built.
    app.json.sort_keys = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return respond_error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return respond_error(
            "ERR_NOT_FOUND", "The requested path does not exist.", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return respond_error(
            "ERR_METHOD_NOT_ALLOWED",
            "The method is not allowed for this path.",
            405,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, HTTPException):
            return respond_error(
                "ERR_HTTP_%d" % err.code,
                err.description or "HTTP error.",
                err.code,
            )
        return respond_error(
            "ERR_INTERNAL", "Internal server error: %s" % err, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
