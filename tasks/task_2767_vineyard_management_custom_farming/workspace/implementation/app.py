"""Vineyard management / custom farming service.

Flask application factory and process entry point. All state lives in the
process-local dictionaries of store.py; nothing is persisted and nothing is
seeded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_core
import routes_harvest
import routes_plans
import routes_spray
import routes_work
from common import ApiError, respond_error


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_plans.bp)
    app.register_blueprint(routes_work.bp)
    app.register_blueprint(routes_spray.bp)
    app.register_blueprint(routes_harvest.bp)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return respond_error(error)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return respond_error(ApiError("ERR_NOT_FOUND", 404, "No such resource."))
        if error.code == 405:
            return respond_error(ApiError(
                "ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed for this path."))
        if error.code == 415:
            return respond_error(ApiError(
                "ERR_INVALID_REQUEST", 400, "Request body is not valid JSON."))
        return respond_error(ApiError(
            "ERR_INVALID_REQUEST", error.code or 400,
            error.description or "Request could not be handled."))

    @app.errorhandler(Exception)
    def _unexpected(error):  # pragma: no cover - safety net
        return respond_error(ApiError(
            "ERR_INTERNAL", 500, "Unexpected server error: %s" % (error,)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
