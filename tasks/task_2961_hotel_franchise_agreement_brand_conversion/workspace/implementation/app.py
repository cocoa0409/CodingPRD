"""Hotel franchise conversion API.

Flask application factory and process entry point.  Every byte of state lives in
the in-memory dictionaries of store.py, so a fresh process is a fresh universe.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_agr
import routes_app
import routes_core
import routes_pip
import routes_qa
import routes_tr
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_app.bp)
    app.register_blueprint(routes_agr.bp)
    app.register_blueprint(routes_pip.bp)
    app.register_blueprint(routes_qa.bp)
    app.register_blueprint(routes_tr.bp)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return envelope.error_response(error)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        status = error.code or 500
        if status == 404:
            return envelope.error_response(
                ApiError("ERR_NOT_FOUND", "No route matches the requested path.", 404)
            )
        if status == 405:
            return envelope.error_response(
                ApiError(
                    "ERR_METHOD_NOT_ALLOWED",
                    "That method is not allowed on this path.",
                    405,
                )
            )
        return envelope.error_response(
            ApiError("ERR_INVALID_REQUEST", error.description, status)
        )

    @app.errorhandler(Exception)
    def _unhandled(error):
        return envelope.error_response(
            ApiError("ERR_INTERNAL", "The server failed to handle the request.", 500)
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
