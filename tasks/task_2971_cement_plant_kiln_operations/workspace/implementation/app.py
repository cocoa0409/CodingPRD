"""Cement Plant Kiln & Clinker Operations API — application entry point.

Storage is entirely in-memory: every launch of start.sh begins with an empty
system, and the only entities that exist are the ones the caller creates through
the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
import routes_master
import routes_design
import routes_kiln
import routes_cement
import routes_commercial


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.register_blueprint(routes_master.bp)
    app.register_blueprint(routes_design.bp)
    app.register_blueprint(routes_kiln.bp)
    app.register_blueprint(routes_cement.bp)
    app.register_blueprint(routes_commercial.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 401:
            return respond_error("ERR_UNAUTHENTICATED", exc.description)
        if exc.code == 403:
            return respond_error("ERR_UNAUTHORIZED", exc.description)
        if exc.code == 404:
            return respond_error("ERR_INVALID_REQUEST",
                                 "No resource is served at that path.", status=404)
        if exc.code == 405:
            return respond_error("ERR_INVALID_REQUEST",
                                 "That method is not allowed on this path.", status=405)
        return respond_error("ERR_INVALID_REQUEST", exc.description or "Bad request")

    @app.errorhandler(Exception)
    def _unexpected(exc):
        app.logger.exception("unhandled error")
        return respond_error("ERR_INVALID_REQUEST",
                             "Unexpected server error.", status=500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True,
            debug=False, use_reloader=False)
