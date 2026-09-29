"""Master Patient Index Identity Integrity API.

Flask entry point. The in-memory store starts empty on every boot: nothing is
seeded, preloaded or hardcoded -- every entity is created through the API.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response, err
import routes_config
import routes_records
import routes_pairs
import routes_merge
import routes_overlay
import routes_fraud


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_config.bp)
    app.register_blueprint(routes_records.bp)
    app.register_blueprint(routes_pairs.bp)
    app.register_blueprint(routes_merge.bp)
    app.register_blueprint(routes_overlay.bp)
    app.register_blueprint(routes_fraud.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        mapped = ApiError("ERR_INVALID_REQUEST", exc.code or 400,
                          exc.description or "Request could not be handled")
        return error_response(mapped)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        mapped = ApiError("ERR_INVALID_REQUEST", 400, "Unhandled request: %s" % exc)
        return error_response(mapped)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
