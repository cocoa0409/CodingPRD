"""Markdown optimisation and season-exit API (Flask entry point)."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (clearance, disposition, executions, items, plans, reads,
                    registry, reviews, vendor)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for module in (reads, registry, items, plans, executions, clearance,
                   vendor, disposition, reviews):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND",
                                           "No such route.", 404))
        if err.code == 405:
            return error_response(ApiError("ERR_VALIDATION",
                                           "Method not allowed.", 400))
        if err.code in (400, 415):
            return error_response(ApiError("ERR_VALIDATION",
                                           "Malformed request.", 400))
        return error_response(ApiError("ERR_VALIDATION", str(err), err.code))

    @app.errorhandler(Exception)
    def _unhandled(err):
        return error_response(ApiError("ERR_VALIDATION",
                                       "Unhandled server error: %s" % err, 500))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
