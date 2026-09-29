"""Label Distribution Recoupment API.

Flask application factory and process entry point.  All state lives in
plain in-memory dictionaries (see db.py); a fresh process therefore starts
with an empty store and the logical clock at its documented default.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (agreements, deals, marketing, releases, reports, runs,
                    setup, statements)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (setup, deals, releases, agreements, marketing, reports, runs,
                   statements):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_not_found(exc):
        return response.error("ERR_INVALID_REQUEST",
                              "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(exc):
        return response.error("ERR_INVALID_REQUEST",
                              "The method is not allowed for this path.", 405)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        return response.error("ERR_INVALID_REQUEST",
                              exc.description or "The request is invalid.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return response.error("ERR_INVALID_REQUEST", str(exc) or "Unhandled error.",
                              500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
